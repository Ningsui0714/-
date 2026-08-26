"""
Task runners: long-running jobs executed by the TaskManager.

Each runner owns its own DB sessions (tasks outlive request sessions) and
updates Task progress + incremental results as it goes.
"""
from datetime import datetime
import asyncio
import os
from typing import List

from sqlalchemy import select

from app.db.database import async_session
from app.models.project import Task, Checkpoint, Roadmap, Project, Chunk, CheckpointChunk, Lecture, LectureVersion, ConceptQuestion, Exercise, Source
from app.services.lecture_agent import LectureAgent


async def run_source_ingestion(task_id: int):
    """Run the existing source pipeline behind a persistent Tutor action."""
    from fastapi import HTTPException
    from app.services.task_manager import update_task, classify_error

    await update_task(
        task_id,
        status="running",
        started_at=datetime.utcnow(),
        progress={"current": 0, "total": 1, "message": "正在读取并整理来源..."},
    )
    async with async_session() as db:
        task = await db.get(Task, task_id)
        if not task:
            return
        project_id = (task.payload or {}).get("project_id")
        source_id = (task.payload or {}).get("source_id")
        try:
            from app.api.phase1 import process_source
            result = await process_source(project_id, source_id, db)
        except HTTPException as exc:
            err = {
                "code": "source_processing",
                "message": str(exc.detail)[:500],
                "guidance": "检查来源地址和网络后重试。",
                "retryable": True,
            }
            await update_task(task_id, status="failed", error=err, finished_at=datetime.utcnow())
            return
        except Exception as exc:
            await update_task(
                task_id, status="failed", error=classify_error(exc), finished_at=datetime.utcnow()
            )
            return

    await update_task(
        task_id,
        status="completed",
        result=result,
        progress={"current": 1, "total": 1, "message": "来源处理完成"},
        finished_at=datetime.utcnow(),
    )
from app.services.task_manager import update_task


def _section_dict(title: str, content: str, keywords, questions) -> dict:
    return {
        "title": title,
        "content": content,
        "keywords": keywords or [],
        "questions": questions or [],
    }


# ── T6: image path rewrite + matplotlib rendering ──

def _rewrite_image_paths(content: str, source_file: str, source_id: int,
                         persist_dir: str = "", all_source_ids: list = None) -> str:
    """Rewrite relative image refs to absolute /api/sources/{sid}/files/... URLs.

    Resolves against BOTH the md's directory and the repo root: some repos
    (e.g. ML-For-Beginners) use repo-root-relative paths in md files; naive
    md-dir resolution would double the prefix (404). With all_source_ids, the
    file is looked up in every source's cache, so images from auxiliary
    sources resolve to their own /api/sources/{sid}/ URL (T10 multi-source).
    """
    import re as _re
    from app.core.config import settings as _settings
    md_dir = os.path.dirname(source_file or "")
    repo_root = _settings.source_cache_dir
    source_ids = all_source_ids or [source_id]

    def _resolve(raw: str) -> str:
        raw = raw.strip()
        if raw.startswith(("http://", "https://", "data:", "/api/", "blob:")):
            return raw
        raw = raw.split("#")[0].split("?")[0]
        cand_md = os.path.normpath(os.path.join(md_dir, raw)).replace(os.sep, "/")
        cand_root = os.path.normpath(raw).replace(os.sep, "/")
        # 1) try every source cache, md-dir resolution first
        for cand in (cand_md, cand_root):
            for sid in source_ids:
                if os.path.isfile(os.path.join(repo_root, str(sid), cand)):
                    return f"/api/sources/{sid}/files/{cand}"
        # 2) fallback: md-dir resolution on the main source (avoids "..")
        return f"/api/sources/{source_id}/files/{cand_md}"

    def _fix_md(m):
        return f"![{m.group(1)}]({_resolve(m.group(2))})"

    def _fix_html(m):
        return f'{m.group(1)}{_resolve(m.group(2))}{m.group(3)}'

    content = _re.sub(r"!\[([^\]]*)\]\(([^)]+)\)", _fix_md, content)
    content = _re.sub(r'(<img[^>]*src=")([^"]+)(")', _fix_html, content)
    return content


def _render_matplotlib_block(code: str, persist_dir: str, idx: int) -> str:
    """Execute a matplotlib code block → save png → return absolute URL (or '')."""
    import subprocess as _sp
    import tempfile as _tf
    import time as _time
    gen_dir = os.path.join(persist_dir, "generated")
    os.makedirs(gen_dir, exist_ok=True)
    out_name = f"fig_{int(_time.time() * 1000)}_{idx}.png"
    out_path = os.path.join(gen_dir, out_name)
    script = (
        "import matplotlib\n"
        "matplotlib.use('Agg')\n"
        "import matplotlib.pyplot as plt\n"
        f"{code}\n"
        f"plt.savefig({out_path!r}, dpi=120, bbox_inches='tight')\n"
    )
    with _tf.NamedTemporaryFile(mode="w", suffix=".py", delete=False, encoding="utf-8") as f:
        f.write(script)
        fpath = f.name
    try:
        # Use the project venv when available, or the packaged sidecar's
        # explicit script mode when running from the desktop bundle.
        from app.services.code_executor import _python_command
        proc = _sp.run(_python_command(fpath), capture_output=True, text=True, timeout=45)
        if proc.returncode != 0 or not os.path.exists(out_path):
            print(f"[matplotlib] render failed: {proc.stderr[-200:]}")
            return ""
        return f"/api/sources/{os.path.basename(persist_dir)}/files/generated/{out_name}"
    except Exception as e:
        print(f"[matplotlib] render error: {type(e).__name__}: {str(e)[:150]}")
        return ""
    finally:
        try:
            os.unlink(fpath)
        except OSError:
            pass


def _repair_markdown_fences(content: str) -> str:
    """Prevent a malformed math fence from swallowing the rest of a section."""
    import re as _re

    output: list[str] = []
    math_open = False
    code_marker = ""
    code_marker_length = 0
    for line in content.split("\n"):
        stripped = line.strip()
        if code_marker:
            output.append(line)
            if _re.fullmatch(
                _re.escape(code_marker) + "{" + str(code_marker_length) + ",}",
                stripped,
            ):
                code_marker = ""
                code_marker_length = 0
            continue

        if stripped == "$$":
            output.append(line)
            math_open = not math_open
            continue

        fence = _re.match(r"^(`{3,}|~{3,})(.*)$", stripped)
        if fence:
            marker, info = fence.groups()
            if math_open:
                if info.strip():
                    output.extend(("$$", line))
                    code_marker = marker[0]
                    code_marker_length = len(marker)
                else:
                    output.append(line.replace(stripped, "$$"))
                math_open = False
                continue
            output.append(line)
            code_marker = marker[0]
            code_marker_length = len(marker)
            continue

        output.append(line)

    if math_open:
        output.append("$$")
    return "\n".join(output)


def _postprocess_section(content: str, source_file: str, source_id: int,
                         persist_dir: str, all_source_ids: list = None) -> str:
    """Repair Markdown, rewrite image paths and render matplotlib blocks."""
    import re as _re
    if not content:
        return content

    # Render matplotlib blocks → replace with image reference
    def _fix_mpl(m):
        url = _render_matplotlib_block(m.group(1), persist_dir, 0)
        if url:
            return f"\n![示意图]({url})\n"
        return "\n*（示意图渲染失败）*\n"

    content = _re.sub(r"```matplotlib\s*\n(.*?)```", _fix_mpl, content, flags=_re.DOTALL)
    content = _repair_markdown_fences(content)
    content = _rewrite_image_paths(content, source_file, source_id, persist_dir, all_source_ids)
    return content


async def _load_lecture_context(checkpoint_id: int):
    """Load checkpoint + project level + scope chunks for a checkpoint."""
    async with async_session() as db:
        checkpoint = (await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        if not checkpoint:
            raise ValueError(f"Checkpoint {checkpoint_id} not found")

        roadmap = (await db.execute(
            select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id)
        )).scalar_one_or_none()
        project = None
        user_level = "beginner"
        if roadmap:
            project = (await db.execute(
                select(Project).where(Project.id == roadmap.project_id)
            )).scalar_one_or_none()
            if project:
                user_level = project.user_level or "beginner"

        chunks_raw = (await db.execute(
            select(Chunk).join(CheckpointChunk)
            .where(CheckpointChunk.checkpoint_id == checkpoint_id)
            .order_by(Chunk.index)
        )).scalars().all()
        chunks = [{"id": c.id, "source_id": c.source_id, "content": c.content, "meta": c.meta_data or {}} for c in chunks_raw]

        return checkpoint, user_level, chunks, (checkpoint.brief or {})


async def run_lecture_generation(task_id: int):
    """
    Lecture generation job:
    plan → per-section generate → save each section to Lecture immediately
    (incremental persistence). Supports resume: sections whose title matches
    the saved ones are reused instead of regenerated.
    """
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    checkpoint_id = (task.payload or {}).get("checkpoint_id")
    resume = bool((task.payload or {}).get("resume"))
    feedback = (task.payload or {}).get("feedback") or ""
    if not checkpoint_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 checkpoint_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    checkpoint, user_level, chunks, brief = await _load_lecture_context(checkpoint_id)

    # T6: derive repo-file cache dir from the main source
    from app.core.config import settings as _settings
    main_source_id = (brief or {}).get("scope", {}).get("main_source_id")
    if not main_source_id and chunks:
        main_source_id = chunks[0].get("source_id")
    persist_dir = os.path.join(_settings.source_cache_dir, str(main_source_id)) if main_source_id else ""

    # T10: all project source ids for cross-source image resolution
    all_source_ids = []
    async with async_session() as db:
        roadmap = (await db.execute(
            select(Roadmap).where(Roadmap.id == checkpoint.roadmap_id)
        )).scalar_one_or_none()
        if roadmap:
            srcs = (await db.execute(
                select(Source).where(Source.project_id == roadmap.project_id)
            )).scalars().all()
            all_source_ids = [s.id for s in srcs]
        project_id = roadmap.project_id if roadmap else None

    if not chunks:
        await update_task(
            task_id, status="failed",
            error={"code": "retrieval_empty",
                   "message": "该关卡没有关联的参考资料切片",
                   "guidance": "请确认来源已处理完成、路线规划已分配切片",
                   "retryable": True},
            finished_at=datetime.utcnow())
        return

    agent = LectureAgent()
    from app.services.animation_agent import AnimationAgent
    anim_agent = AnimationAgent()

    # ── Plan ──
    # Resume: reuse the persisted plan (stable section reuse — T10).
    # Fresh: replan and persist the new plan.
    plan_sections = None
    if resume:
        async with async_session() as db:
            lec = (await db.execute(
                select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
            )).scalar_one_or_none()
            if lec and lec.plan:
                plan_sections = lec.plan

    if plan_sections is None:
        await update_task(task_id, progress={"current": 0, "total": 0, "message": "正在准备讲义结构..."})
        try:
            skeleton = []
            scope_files = (brief or {}).get("scope", {}).get("files") or []
            if scope_files:
                skeleton = agent.build_structure_skeleton(brief, chunks)
            if skeleton and not feedback.strip():
                # The repository structure is already a deterministic outline.
                # Do not spend another long model round trip re-planning it
                # before the first visible section can be generated.  This
                # restores the incremental, observable generation behavior.
                plan_sections = [{
                    "title": item["title"],
                    "keywords": [],
                    "goal": f"学习 {item['title']}",
                    "source_file": item["file"],
                    "source_heading": item.get("heading", ""),
                    "chunk_ids": item["chunk_ids"],
                    "adjust_reason": "keep",
                } for item in skeleton]
            else:
                plan_sections = await agent.plan_lecture(
                    checkpoint.title, checkpoint.description or "", user_level, chunks, brief=brief, feedback=feedback
                )
        except Exception as e:
            from app.services.task_manager import classify_error
            err = classify_error(e)
            await update_task(task_id, status="failed", error=err, finished_at=datetime.utcnow())
            return

    # Filter chunk_ids that no longer exist (sources may have been re-processed)
    if plan_sections:
        valid_ids = {c["id"] for c in chunks}
        for ps in plan_sections:
            ids = ps.get("chunk_ids") or []
            ps["chunk_ids"] = [i for i in ids if i in valid_ids]

    total = len(plan_sections)
    if total == 0:
        plan_sections = [{"title": checkpoint.title, "keywords": [], "goal": checkpoint.description or ""}]
        total = 1

    await update_task(task_id, progress={
        "current": 0,
        "total": total,
        "message": f"大纲已就绪，共 {total} 节，准备生成第 1 节...",
    })

    # ── Load existing lecture (for resume / incremental append) ──
    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        if not lecture:
            lecture = Lecture(checkpoint_id=checkpoint_id, sections=[], status="draft")
            db.add(lecture)
            await db.commit()
            await db.refresh(lecture)
        if not resume:
            # T5: snapshot the published lecture before it gets overwritten
            if lecture.status == "published" and lecture.sections:
                db.add(LectureVersion(
                    checkpoint_id=checkpoint_id,
                    sections=list(lecture.sections),
                    source_version=int(lecture.version or 1),
                    reason="regenerate_before",
                ))
            # Fresh generation: clear stale partial content + persist new plan
            lecture.sections = []
            lecture.plan = plan_sections
            lecture.status = "draft"
            lecture.version = int(lecture.version or 1) + 1
            await db.commit()
        saved = list(lecture.sections or [])

    # ── Generate each section (reuse saved ones on resume) ──
    cited_all = []
    used_images: set = set()  # T6: one lecture never repeats the same image

    def _dedup_images(content: str) -> str:
        import re as _re
        def fix(m):
            url = m.group(1)
            if url in used_images:
                return ""  # already used in an earlier section → drop
            used_images.add(url)
            return m.group(0)
        return _re.sub(r"!\[[^\]]*\]\((/api/sources/\d+/files/[^)]+)\)", fix, content)

    for i, ps in enumerate(plan_sections):
        title = ps.get("title", f"第{i+1}节")

        # Reuse on resume when the saved section matches this plan position
        if resume and i < len(saved) and saved[i].get("title") == title:
            content = saved[i].get("content", "")
            questions = saved[i].get("questions", [])
        else:
            await update_task(task_id, progress={
                "current": i,
                "total": total,
                "message": f"正在生成第 {i + 1}/{total} 节：{title}",
            })
            try:
                content = await agent.generate_section(
                    checkpoint.title, ps, chunks,
                    section_keywords=ps.get("keywords", []),
                    brief=brief,
                    section_chunk_ids=ps.get("chunk_ids"),
                    used_images=used_images,
                    feedback=feedback,
                )
            except Exception as e:
                # One retry per section, then fail the task (partial remains)
                try:
                    content = await agent.generate_section(
                        checkpoint.title, ps, chunks,
                        section_keywords=ps.get("keywords", []),
                        brief=brief,
                        section_chunk_ids=ps.get("chunk_ids"),
                        used_images=used_images,
                        feedback=feedback,
                    )
                except Exception as e2:
                    from app.services.task_manager import classify_error
                    err = classify_error(e2)
                    await update_task(
                        task_id, status="failed", error=err,
                        progress={"current": i, "total": total,
                                  "message": f"第{i+1}节生成失败，已保留前 {i} 节"},
                        finished_at=datetime.utcnow())
                    return
            questions = agent._extract_questions(content)
            # T6: rewrite image paths + render matplotlib blocks
            content = _postprocess_section(
                content, ps.get("source_file", ""), main_source_id or 0,
                persist_dir, all_source_ids)
            # Hard dedup: drop image refs already used in earlier sections
            content = _dedup_images(content)
            questions = agent._extract_questions(content)

            # ── process-animator：内容 → 动画/静态图，注入占位符（失败不阻塞） ──
            try:
                async with async_session() as adb:
                    vis = await anim_agent.maybe_create_visual(
                        project_id, checkpoint_id, i, content, adb)
                    if vis:
                        content = content.rstrip() + f"\n\n:::process-anim {vis['id']}\n"
            except Exception:
                pass

        cited_all.extend(agent._extract_cited_chunks(content))
        sec = _section_dict(title, content, ps.get("keywords", []), questions)
        sec["source_file"] = ps.get("source_file", "")
        sec["source_heading"] = ps.get("source_heading", "")
        sec["cited_chunks"] = agent._extract_cited_chunks(content)

        # Incremental save: replace section at index (fresh) or append
        async with async_session() as db:
            lecture = (await db.execute(
                select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
            )).scalar_one_or_none()
            if lecture is None:
                lecture = Lecture(checkpoint_id=checkpoint_id, sections=[], status="draft")
                db.add(lecture)
            sections = list(lecture.sections or [])
            while len(sections) <= i:
                sections.append(None)
            sections[i] = sec
            lecture.sections = sections
            lecture.status = "draft"
            await db.commit()

        await update_task(task_id, progress={
            "current": i + 1, "total": total,
            "message": f"生成中... {i+1}/{total}",
        })

    # ── Finalize ──
    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        if lecture:
            lecture.status = "published"
            lecture.version = int(lecture.version or 1) + 1
            from app.api.phase2 import _reanchor_lecture_annotations
            await _reanchor_lecture_annotations(
                db, lecture, list(lecture.sections or []), lecture.version,
            )
        checkpoint = (await db.execute(
            select(Checkpoint).where(Checkpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        if checkpoint and checkpoint.learning_status not in {"completed", "verification_due"}:
            checkpoint.learning_status = "in_progress"

        # T3 write-back: citation feedback → brief retrieval policy
        if checkpoint and checkpoint.brief:
            cp_chunks = (await db.execute(
                select(Chunk.id).join(CheckpointChunk)
                .where(CheckpointChunk.checkpoint_id == checkpoint_id)
            )).scalars().all()
            scope_ids = set(cp_chunks)
            cited = set(cited_all)
            cited_in_scope = sorted(cited & scope_ids)
            new_brief = dict(checkpoint.brief)
            rp = dict(new_brief.get("retrieval_policy") or {})
            old_boost = set(rp.get("boost_chunk_ids") or [])
            rp["boost_chunk_ids"] = sorted(old_boost | set(cited_in_scope))
            new_brief["retrieval_policy"] = rp
            stats = dict(new_brief.get("retrieval_stats") or {})
            new_brief["retrieval_stats"] = {
                "version": stats.get("version", 0) + 1,
                "cited_chunks": sorted(cited),
                "cited_in_scope": cited_in_scope,
                "cited_out_of_scope": sorted(cited - scope_ids),
                "sections_count": len(plan_sections),
            }
            checkpoint.brief = new_brief
        await db.commit()
        from app.services.workspace_files import sync_managed_layout_for_project
        roadmap = await db.get(Roadmap, checkpoint.roadmap_id) if checkpoint else None
        if roadmap:
            await sync_managed_layout_for_project(db, roadmap.project_id)

    from app.services.progress import mark_lecture_generated
    await mark_lecture_generated(checkpoint_id)

    await update_task(
        task_id, status="completed",
        progress={"current": total, "total": total, "message": f"完成！共 {total} 节"},
        result={"sections_count": total},
        finished_at=datetime.utcnow(),
    )


# ── T6: image captioning — free tier (md-context + OCR + SVG) / api enhance ──

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
_OCR_EXTS = {".png", ".jpg", ".jpeg"}


def _scan_images(persist_dir: str, include_svg: bool = False) -> List[str]:
    """List image files (repo-relative paths), skipping generated/."""
    out = []
    for root, dirs, files in os.walk(persist_dir):
        if os.path.basename(root) == "generated":
            continue
        rel_dir = os.path.relpath(root, persist_dir)
        for fn in files:
            ext = f".{fn.split('.')[-1].lower()}" if "." in fn else ""
            if ext in _IMAGE_EXTS or (include_svg and ext == ".svg"):
                rel = os.path.join(rel_dir, fn) if rel_dir != "." else fn
                out.append(rel.replace(os.sep, "/"))
    return sorted(out)


def _ocr_image(path: str) -> List[str]:
    """Apple Vision OCR (local, free): extract in-image text terms."""
    try:
        from ocrmac import ocrmac
        res = ocrmac.OCR(path).recognize()
        terms = []
        for t, conf, _box in res:
            t = (t or "").strip()
            if conf < 0.3 or len(t) < 2:
                continue
            if t not in terms:
                terms.append(t)
        return terms[:12]
    except Exception as e:
        print(f"[ocr] {os.path.basename(path)} failed: {type(e).__name__}: {str(e)[:100]}")
        return []


def _svg_analysis(path: str):
    """Structure stats for SVG diagrams (free, deterministic)."""
    try:
        import xml.etree.ElementTree as ET
        from collections import Counter
        tree = ET.parse(path)
        root = tree.getroot()
        counts = Counter(el.tag.split("}")[-1] for el in root.iter())
        nodes = counts.get("rect", 0) + counts.get("circle", 0) + counts.get("ellipse", 0) + counts.get("polygon", 0)
        lines = counts.get("path", 0) + counts.get("line", 0)
        texts = sum(1 for t in root.findall(".//{*}text") if (t.text or "").strip())
        stem = os.path.basename(path)[:-4]
        return (f"SVG 结构图：{nodes} 个节点形状，{lines} 条线/路径，{texts} 处文本标注"
                f"（文件名: {stem}）")
    except Exception:
        return None


def _extract_md_context(md_rel: str, image_rel: str, persist_dir: str):
    """Heading + surrounding text + alt from the md file referencing the image."""
    import re as _re
    full = os.path.join(persist_dir, md_rel)
    try:
        with open(full, encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return None
    md_dir = os.path.dirname(md_rel)
    for m in _re.finditer(r"!\[([^\]]*)\]\(\s*([^)]+?)\s*\)", content):
        raw = m.group(2).strip()
        if raw.startswith(("http://", "https://", "data:")):
            continue
        resolved = os.path.normpath(os.path.join(md_dir, raw)).replace(os.sep, "/")
        if resolved == image_rel or image_rel in resolved or resolved in image_rel:
            pre = content[:m.start()]
            heads = _re.findall(r"^#{1,6}\s+(.+)$", pre, _re.MULTILINE)
            heading = heads[-1] if heads else ""
            alt = m.group(1).strip()
            before = content[max(0, m.start() - 120):m.start()].strip()
            after = content[m.end():m.end() + 120].strip()
            ctx = " ".join(x for x in (before, after) if x).strip()[:240]
            return {"heading": heading, "alt": alt, "context": ctx}
    return None


def _free_caption(rel: str, persist_dir: str, md_map: dict) -> tuple:
    """Free-tier caption: md context + OCR/SVG structure. Returns (caption, needs_api).

    OCR is skipped for small images (<20KB) — they are icons/decorations where
    OCR yields nothing; md context (if any) suffices. This cuts OCR work ~40%
    on image-heavy repos (e.g. ML-For-Beginners: 8.5k images, 98% webp).
    """
    md_rel = md_map.get(rel)
    ctx = _extract_md_context(md_rel, rel, persist_dir) if md_rel else None
    fpath = os.path.join(persist_dir, rel)
    try:
        size = os.path.getsize(fpath)
    except OSError:
        size = 0
    ext = rel.split(".")[-1].lower()
    if ext == "svg":
        struct = _svg_analysis(fpath)
        ocr_terms = []
    elif ext in _OCR_EXTS and size >= 20 * 1024:
        ocr_terms = _ocr_image(fpath)
        struct = None
    else:  # small images / gif/webp-small / bmp: no OCR, context only
        ocr_terms, struct = [], None

    parts = []
    if ctx:
        head = f"（{ctx['heading']}）" if ctx["heading"] else ""
        parts.append(f"{md_rel}{head}配图")
        if ctx["context"]:
            parts.append(ctx["context"])
    if ocr_terms:
        parts.append("图内标注: " + ", ".join(ocr_terms))
    if struct:
        parts.append(struct)
    if not (ctx or ocr_terms or struct):
        if size < 20 * 1024:
            # decorative small icon — not worth paid API understanding
            return "（装饰性小图，未做文字识别）", False
        return "（纯图形/照片，无文字标注）", True
    return "；".join(parts)[:300], False


def _map_images_to_md(persist_dir: str) -> dict:
    """Map image path → first referencing md file (relative to repo root)."""
    import re as _re
    mapping = {}
    for root, dirs, files in os.walk(persist_dir):
        dirs[:] = [d for d in dirs if d != "generated"]
        for fn in files:
            if not fn.endswith((".md", ".rst")):
                continue
            md_path = os.path.join(root, fn)
            rel_md = os.path.relpath(md_path, persist_dir).replace(os.sep, "/")
            try:
                with open(md_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except OSError:
                continue
            md_dir = os.path.dirname(rel_md)
            for m in _re.finditer(r"!\[.*?\]\(\s*(.*?)\s*\)", content):
                raw = m.group(1).strip()
                if raw.startswith(("http://", "https://", "data:")):
                    continue
                resolved = os.path.normpath(os.path.join(md_dir, raw)).replace(os.sep, "/")
                mapping.setdefault(resolved, rel_md)
    return mapping


async def run_image_captioning(task_id: int):
    """Caption repo images → upsert as image chunks (caption-as-text RAG).

    mode=free (default): md-context + Apple Vision OCR + SVG structure — zero cost.
    mode=api: only images flagged needs_api get Moonshot vision captions.
    Idempotent: free mode skips already-captioned images; api mode only touches
    needs_api ones; toggling between modes never destroys existing captions.
    """
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    source_id = (task.payload or {}).get("source_id")
    if not source_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 source_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    from app.core.config import settings as _settings
    persist_dir = os.path.join(_settings.source_cache_dir, str(source_id))
    mode = (task.payload or {}).get("mode", "free")
    images = _scan_images(persist_dir, include_svg=(mode == "free"))
    limit = (task.payload or {}).get("limit")
    if limit:
        images = images[: int(limit)]

    md_map = _map_images_to_md(persist_dir)
    project_id = (task.payload or {}).get("project_id")

    # Precompute checkpoint → scope files (to auto-link image chunks)
    cp_scope = {}  # cp_id -> set(files)
    if project_id:
        async with async_session() as db:
            cps = (await db.execute(
                select(Checkpoint).join(Roadmap).where(Roadmap.project_id == project_id)
            )).scalars().all()
            for cp in cps:
                files = set(((cp.brief or {}).get("scope") or {}).get("files") or [])
                if files:
                    cp_scope[cp.id] = files

    from sqlalchemy import func as _func
    async with async_session() as db:
        next_index = (await db.execute(
            select(_func.max(Chunk.index)).where(Chunk.source_id == source_id)
        )).scalar() or 0

    async def _get_existing(rel: str):
        async with async_session() as db:
            return (await db.execute(
                select(Chunk).where(
                    Chunk.source_id == source_id,
                    Chunk.meta_data["image_path"].as_string() == rel,
                )
            )).scalars().all()

    # api mode: only needs_api images (python-side filter — robust across
    # bool/string storage since SQLite json_extract turns JSON true into int 1)
    if mode == "api":
        from app.services import vision
        needs = set()
        async with async_session() as db:
            rows = (await db.execute(
                select(Chunk).where(Chunk.source_id == source_id)
            )).scalars().all()
            for c in rows:
                v = (c.meta_data or {}).get("needs_api")
                if v in (True, "true", "1", 1):
                    needs.add((c.meta_data or {}).get("image_path"))
        images = [r for r in images if r in needs]
    else:
        from app.services import vision  # noqa: F401  (kept for api mode import parity)

    total = len(images)
    if total == 0:
        msg = {"free": "没有需要处理的图片（全部已有描述或无需处理）",
               "api": "没有标记为需要 API 理解的图片（免费管线已覆盖）"}.get(mode, "无待处理图片")
        await update_task(task_id, status="completed",
                          progress={"current": 0, "total": 0, "message": msg},
                          result={"captioned": 0, "failed": 0, "skipped": 0, "images": 0},
                          finished_at=datetime.utcnow())
        return

    captioned = failed = skipped = 0
    sem = asyncio.Semaphore(4 if mode == "free" else 3)

    for i, rel in enumerate(images):
        await update_task(task_id, progress={
            "current": i, "total": total,
            "message": f"{'理解' if mode == 'api' else '分析'}图片 {i + 1}/{total}: {rel[-40:]}",
        })

        # Idempotency: free mode keeps existing captions (kimi/free) untouched
        existing = await _get_existing(rel)
        if mode == "free" and existing and (existing[0].meta_data or {}).get("caption"):
            skipped += 1
            continue

        if mode == "free":
            caption, needs_api = _free_caption(rel, persist_dir, md_map)
            caption_source = "free"
            if rel.endswith(".svg"):
                # kimi vision can't read SVG — API enhance is raster-only
                needs_api = False
        else:
            try:
                caption = await asyncio.to_thread(
                    vision.caption_image, os.path.join(persist_dir, rel))
                caption_source = "api"
                needs_api = False
            except Exception as e:
                failed += 1
                print(f"[caption/api] {rel} failed: {type(e).__name__}: {str(e)[:120]}")
                continue

        ref_md = md_map.get(rel, "")
        content = f"【图片】{rel}: {caption}"
        # needs_api stored as STRING — SQLite json_extract turns JSON true into int 1
        meta = {
            "type": "image",
            "source_type": "github",
            "file": ref_md or rel,
            "image_path": rel,
            "caption": caption,
            "caption_source": caption_source,
            "needs_api": "true" if needs_api else "false",
            "headings": [],
            "heading_chain": [],
        }
        async with async_session() as db:
            if existing:
                chunk = existing[0]
                chunk.content = content
                chunk.meta_data = meta
            else:
                next_index += 1
                chunk = Chunk(
                    source_id=source_id,
                    index=next_index,
                    content=content,
                    tokens=len(content) // 4,
                    meta_data=meta,
                )
                db.add(chunk)
                await db.flush()

            # Auto-link to checkpoints whose scope includes the referencing md file
            if ref_md and cp_scope:
                for cp_id, files in cp_scope.items():
                    if ref_md in files:
                        exists = (await db.execute(
                            select(CheckpointChunk).where(
                                CheckpointChunk.checkpoint_id == cp_id,
                                CheckpointChunk.chunk_id == chunk.id,
                            )
                        )).scalar_one_or_none()
                        if not exists:
                            db.add(CheckpointChunk(checkpoint_id=cp_id, chunk_id=chunk.id))
            await db.commit()
        captioned += 1

    await update_task(
        task_id, status="completed",
        progress={"current": total, "total": total,
                  "message": f"完成：{captioned} 张已处理（跳过 {skipped}，失败 {failed}）"},
        result={"captioned": captioned, "failed": failed, "skipped": skipped, "images": total},
        finished_at=datetime.utcnow(),
    )


# ── T7: concept question generation ──

async def run_concept_generation(task_id: int):
    """Generate source-grounded formative checks for one checkpoint."""
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    checkpoint_id = (task.payload or {}).get("checkpoint_id")
    if not checkpoint_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 checkpoint_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    checkpoint, user_level, chunks, brief = await _load_lecture_context(checkpoint_id)
    if not chunks:
        await update_task(task_id, status="failed",
                          error={"code": "retrieval_empty",
                                 "message": "该关卡没有关联的参考资料切片",
                                 "guidance": "请确认来源已处理完成、路线规划已分配切片",
                                 "retryable": True},
                          finished_at=datetime.utcnow())
        return

    # Lecture sections for context
    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        sections = lecture.sections or [] if lecture else []

    # Retrieve the most relevant chunks for question context
    from app.services.lecture_agent import LectureAgent
    agent = LectureAgent()
    rp = (brief or {}).get("retrieval_policy") or {}
    relevant = await agent._retrieve_relevant_chunks(
        f"{checkpoint.title} {checkpoint.description or ''}", chunks, top_k=12,
        boost_ids=rp.get("boost_chunk_ids"),
        boost_weight=rp.get("boost_weight", 1.5),
        scope_files=(brief or {}).get("scope", {}).get("files"),
    )

    await update_task(task_id, progress={"current": 0, "total": 0, "message": "正在按学习目标设计并校验题目..."})
    from app.services.concept_agent import ConceptAgent
    cagent = ConceptAgent()
    questions = await cagent.generate(
        checkpoint.title, checkpoint.description or "", user_level,
        sections, relevant,
    )

    if not questions:
        await update_task(
            task_id, status="failed",
            error={"code": "llm_format",
                   "message": "命题失败：没有生成符合关卡目标与格式约束的题目",
                   "guidance": "请重试；若持续出现，请检查关卡目标、讲义和来源切片是否充分",
                   "retryable": True},
            progress={"current": 0, "total": 0, "message": "命题失败"},
            finished_at=datetime.utcnow())
        return

    # Replace old questions (fresh generation)
    async with async_session() as db:
        old = (await db.execute(
            select(ConceptQuestion).where(ConceptQuestion.checkpoint_id == checkpoint_id)
        )).scalars().all()
        for q in old:
            await db.delete(q)
        for i, q in enumerate(questions):
            db.add(ConceptQuestion(
                checkpoint_id=checkpoint_id,
                question=q["question"],
                options=q["options"],
                answer_indexes=q["answer_indexes"],
                q_type=q["q_type"],
                difficulty=q["difficulty"],
                explanation=q["explanation"],
                source_chunk_ids=q.get("source_chunk_ids", []),
                code=q["code"],
                assessment_meta={
                    "mode": "formative",
                    "target_concepts": q.get("target_concepts", []),
                    "learning_target": q.get("learning_target", ""),
                    "evidence_claim": q.get("evidence_claim", ""),
                    "response_format": q["q_type"],
                    "design_status": "provisional",
                    "evidence_target": {"knowledge": "concept_attempt"},
                },
                expected_output=q["expected_output"],
                order=i + 1,
            ))
        await db.commit()
    await update_task(
        task_id, status="completed",
        progress={"current": len(questions), "total": len(questions),
                  "message": f"完成！共 {len(questions)} 道概念题"},
        result={"questions_count": len(questions)},
        finished_at=datetime.utcnow(),
    )


# ── T8: exercise generation (blueprint → verify) ──

async def run_exercise_generation(task_id: int):
    """Generate coding exercises with executable verification (T8)."""
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    checkpoint_id = (task.payload or {}).get("checkpoint_id")
    if not checkpoint_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 checkpoint_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    checkpoint, user_level, chunks, brief = await _load_lecture_context(checkpoint_id)
    if not chunks:
        await update_task(task_id, status="failed",
                          error={"code": "retrieval_empty",
                                 "message": "该关卡没有关联的参考资料切片",
                                 "guidance": "请确认来源已处理完成、路线规划已分配切片",
                                 "retryable": True},
                          finished_at=datetime.utcnow())
        return

    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        sections = lecture.sections or [] if lecture else []

    from app.services.lecture_agent import LectureAgent
    agent = LectureAgent()
    rp = (brief or {}).get("retrieval_policy") or {}
    relevant = await agent._retrieve_relevant_chunks(
        f"{checkpoint.title} {checkpoint.description or ''}", chunks, top_k=12,
        boost_ids=rp.get("boost_chunk_ids"),
        boost_weight=rp.get("boost_weight", 1.5),
        scope_files=(brief or {}).get("scope", {}).get("files"),
    )

    lecture_text = "\n\n".join(s.get("content", "")[:1200] for s in sections[:3])
    chunk_text = "\n".join(c["content"][:600] for c in relevant[:6])

    await update_task(task_id, progress={"current": 0, "total": 0, "message": "正在命题蓝图..."})
    from app.services.exercise_agent import ExerciseAgent
    eagent = ExerciseAgent()
    try:
        def _cb(done, total):
            asyncio.create_task(update_task(
                task_id, progress={"current": done, "total": total,
                                   "message": f"生成中... {done}/{total} 题通过验证"}))
        exercises = await eagent.generate_all(
            checkpoint.title, checkpoint.description or "", lecture_text, chunk_text,
            progress_cb=_cb)
    except Exception as e:
        from app.services.task_manager import classify_error
        err = classify_error(e)
        await update_task(task_id, status="failed", error=err, finished_at=datetime.utcnow())
        return

    if not exercises:
        await update_task(
            task_id, status="failed",
            error={"code": "llm_format",
                   "message": "命题失败：没有题目通过可执行验证",
                   "guidance": "请重试；若持续出现，可能是内容不适合出编程题",
                   "retryable": True},
            progress={"current": 0, "total": 0, "message": "命题失败"},
            finished_at=datetime.utcnow())
        return

    # Replace old exercises (fresh generation)
    async with async_session() as db:
        old = (await db.execute(
            select(Exercise).where(Exercise.checkpoint_id == checkpoint_id)
        )).scalars().all()
        for e in old:
            await db.delete(e)
        for i, ex in enumerate(exercises):
            db.add(Exercise(
                checkpoint_id=checkpoint_id,
                title=ex["title"],
                description=ex["description"],
                starter_code=ex["starter_code"],
                solution=ex["solution"],
                test_cases=ex["test_cases"],
                hints=ex["hints"],
                order=i + 1,
                assessment_meta={
                    "mode": "practice",
                    "target_skills": ex.get("target_skills", []),
                    "independence_criteria": ["tests_pass", "no_guidance"],
                    "evidence_target": {"practice": "independent_success"},
                },
            ))
        await db.commit()
        from app.services.workspace_files import sync_managed_layout_for_project
        roadmap = (await db.execute(
            select(Roadmap).join(Checkpoint, Checkpoint.roadmap_id == Roadmap.id)
            .where(Checkpoint.id == checkpoint_id)
        )).scalar_one_or_none()
        if roadmap:
            await sync_managed_layout_for_project(db, roadmap.project_id)

    await update_task(
        task_id, status="completed",
        progress={"current": len(exercises), "total": len(exercises),
                  "message": f"完成！{len(exercises)} 道题通过验证"},
        result={"exercises_count": len(exercises)},
        finished_at=datetime.utcnow(),
    )


# ── Concept graph generation (concept map) ──

async def run_concept_graph_generation(task_id: int):
    """Extract a concept knowledge graph from the lecture (single LLM call)."""
    task = await update_task(task_id, status="running", started_at=datetime.utcnow())
    if not task:
        return
    checkpoint_id = (task.payload or {}).get("checkpoint_id")
    if not checkpoint_id:
        await update_task(task_id, status="failed",
                          error={"code": "internal", "message": "payload 缺少 checkpoint_id",
                                 "guidance": "内部错误", "retryable": False},
                          finished_at=datetime.utcnow())
        return

    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        if not lecture or not lecture.sections:
            await update_task(task_id, status="failed",
                              error={"code": "retrieval_empty",
                                     "message": "该关卡还没有讲义，无法生成概念图谱",
                                     "guidance": "请先生成讲义",
                                     "retryable": True},
                              finished_at=datetime.utcnow())
            return
        sections = lecture.sections

    await update_task(task_id, progress={"current": 0, "total": 0, "message": "正在提取概念与关系..."})
    from app.services.concept_agent import ConceptAgent
    graph = await ConceptAgent().generate_graph(sections)
    if not graph.get("nodes"):
        await update_task(task_id, status="failed",
                          error={"code": "llm_format",
                                 "message": "概念提取失败",
                                 "guidance": "请重试",
                                 "retryable": True},
                          finished_at=datetime.utcnow())
        return

    async with async_session() as db:
        lecture = (await db.execute(
            select(Lecture).where(Lecture.checkpoint_id == checkpoint_id)
        )).scalar_one_or_none()
        if lecture:
            lecture.concept_graph = graph
            await db.commit()

    await update_task(
        task_id, status="completed",
        progress={"current": len(graph["nodes"]), "total": len(graph["nodes"]),
                  "message": f"完成！{len(graph['nodes'])} 个概念，{len(graph['edges'])} 条关系"},
        result={"nodes": len(graph["nodes"]), "edges": len(graph["edges"])},
        finished_at=datetime.utcnow(),
    )
