"""
API routes for Phase 1 features:
- Source processing
- Roadmap agent chat
"""
from fastapi import APIRouter, Depends, HTTPException, Body
import json
import os
import shutil
from app.core.config import settings
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from typing import List

from app.db.database import get_db
from app.models.learning import AgentAction, AgentSession, LearnerProfile, LearningProjectProposal
from app.models.project import Project, Source, Chunk, Roadmap, Checkpoint, CheckpointChunk, Task
from app.schemas.project import (
    AgentChatRequest, AgentChatResponse,
)
from app.services.chunker import SourceProcessor
from app.services.roadmap_agent import RoadmapAgent
from app.services.learning_runtime import get_kernel_projection
from app.services.auth import (
    CurrentLearner, get_current_learner, require_owned_project,
    require_owned_source,
)

router = APIRouter()
chunker = SourceProcessor()


def _repository_knowledge_domains(sources: list[Source]) -> list[dict]:
    """Return compact, source-grounded topic context for roadmap planning.

    These labels describe what a repository contains.  They intentionally stay
    outside the five-kernel projection: a source outline is course context, not
    a claim about what the learner knows or should be scored on.
    """
    result = []
    for source in sources:
        meta = source.meta_data or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except json.JSONDecodeError:
                meta = {}
        analysis = dict(meta.get("repo_analysis") or {})
        seen: set[str] = set()
        domains = []

        def add(label: object, evidence: str) -> None:
            value = " ".join(str(label or "").split())[:160]
            key = value.casefold()
            if value and key not in seen and len(domains) < 12:
                seen.add(key)
                domains.append({"label": value, "evidence": evidence})

        for item in analysis.get("readme_toc") or []:
            if isinstance(item, dict):
                add(item.get("title"), "README 目录")
        for group in analysis.get("dir_groups") or []:
            if isinstance(group, dict) and group.get("is_chapter"):
                add(group.get("name") or group.get("dir"), "章节目录")
        # Some repositories do not have a usable TOC or chapter folders.  File
        # summaries still provide an inspectable, non-LLM-invented fallback.
        if not domains:
            for path in (analysis.get("file_summaries") or {}).keys():
                add(path, "文件摘要路径")

        if domains:
            result.append({
                "source_id": source.id,
                "role": source.role or "main",
                "type": source.type,
                "structure_logic": analysis.get("structure_logic", "mixed"),
                "domains": domains,
            })
    return result


async def _roadmap_planning_context(
    db: AsyncSession,
    current: CurrentLearner,
    project_id: int,
) -> dict:
    """Build private planning context without turning proposal stages into a roadmap."""
    profile = await db.get(LearnerProfile, current.learner.id)
    proposal = (await db.execute(
        select(LearningProjectProposal)
        .where(
            LearningProjectProposal.learner_id == current.learner.id,
            LearningProjectProposal.accepted_project_id == project_id,
            LearningProjectProposal.status == "accepted",
        )
        .order_by(LearningProjectProposal.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    project_session = (await db.execute(
        select(AgentSession)
        .where(
            AgentSession.learner_id == current.learner.id,
            AgentSession.project_id == project_id,
            AgentSession.session_type == "project",
            AgentSession.status == "active",
        )
        .order_by(AgentSession.updated_at.desc())
        .limit(1)
    )).scalar_one_or_none()
    sources = list((await db.execute(
        select(Source).where(Source.project_id == project_id)
    )).scalars().all())

    proposal_artifact = dict(proposal.artifact or {}) if proposal else {}
    return {
        "input_policy": {
            "content_source": "processed_project_sources",
            "adaptation_source": "learner_profile_and_five_kernel_memory",
            "decision_source": "current_project_dialogue_and_explicit_confirmation",
            "stage_preview_weight": "low",
        },
        "learner_profile": {
            "education_stage": profile.education_stage,
            "background": profile.background,
            "focus_areas": list(profile.focus_areas or []),
            "weekly_hours": profile.weekly_hours,
            "preferred_modes": list(profile.preferred_modes or []),
            "career_goal": profile.career_goal,
            "career_goal_status": profile.career_goal_status,
        } if profile else {},
        "five_kernel_memory": await get_kernel_projection(db, current.learner.id),
        "repository_knowledge_domains": _repository_knowledge_domains(sources),
        "session_handoff": dict(project_session.context_summary or {}) if project_session else {},
        "proposal_reference": {
            "proposal_id": proposal.id,
            "revision": proposal.revision,
            "learning_goal": proposal_artifact.get("learning_goal", ""),
            "practice_goal": proposal_artifact.get("practice_goal", ""),
            "estimated_effort": proposal_artifact.get("estimated_effort", ""),
            "acceptance_criteria": list(proposal_artifact.get("acceptance_criteria") or []),
            "risks": list(proposal_artifact.get("risks") or []),
            "stage_preview": list(proposal_artifact.get("milestones") or []),
            "usage": "soft_reference_only",
        } if proposal else {},
    }


def _count_images(persist_dir: str) -> int:
    """Count image files in the repo cache (T6)."""
    count = 0
    for root, dirs, files in os.walk(persist_dir):
        if os.path.basename(root) == "generated":
            continue
        for fn in files:
            ext = f".{fn.split('.')[-1].lower()}" if "." in fn else ""
            if ext in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".bmp"}:
                count += 1
    return count


def _source_input(source: Source) -> str:
    """Resolve the processing input without treating it as a workspace file."""
    if source.type == "file":
        upload = dict(source.meta_data or {}).get("upload") or {}
        stored_path = upload.get("stored_path")
        if stored_path:
            return stored_path
    return source.url


# ── Source Processing ──

@router.post("/projects/{project_id}/sources/{source_id}/process")
async def process_source(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Fetch and chunk a source."""
    await require_owned_project(db, current.learner.id, project_id)
    source = await require_owned_source(db, current.learner.id, source_id, project_id)

    # Update status
    source.status = "processing"
    await db.commit()

    # Checkpoints affected by this source's chunks (their links will break)
    affected_cp_ids = (await db.execute(
        select(Checkpoint.id)
        .join(CheckpointChunk).join(Chunk)
        .where(Chunk.source_id == source.id)
        .distinct()
    )).scalars().all()

    # Source cache (T6): clear old derived files; never write to a project workspace.
    persist_dir = os.path.join(settings.source_cache_dir, str(source.id))
    if os.path.exists(persist_dir):
        shutil.rmtree(persist_dir, ignore_errors=True)
    os.makedirs(persist_dir, exist_ok=True)

    try:
        # Process the source (now returns {chunks, source_meta})
        result_data = await chunker.process_source(source.type, _source_input(source), persist_dir=persist_dir)
        chunks_data = result_data["chunks"]
        source_meta = result_data.get("source_meta", {})
        source_meta["source_cache_dir"] = persist_dir
        source_meta["image_files"] = _count_images(persist_dir)

        # Store directory structure/toc as source metadata
        if source_meta:
            try:
                source.meta_data = {**(source.meta_data or {}), "repo_analysis": source_meta}
            except AttributeError:
                pass  # meta_data column may not exist on old DB

        # Delete previous chunks for this source
        old = await db.execute(select(Chunk).where(Chunk.source_id == source.id))
        for c in old.scalars().all():
            await db.delete(c)

        # Insert new chunks with rich metadata
        for cd in chunks_data:
            chunk = Chunk(
                source_id=source.id,
                index=cd["index"],
                content=cd["content"],
                tokens=cd["tokens"],
                meta_data=cd.get("meta", {}),
            )
            db.add(chunk)

        # Mark affected checkpoints' briefs as needing resync (chunk ids changed)
        for cp_id in affected_cp_ids:
            cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == cp_id))).scalar_one_or_none()
            if cp and cp.brief:
                new_brief = dict(cp.brief)
                new_brief["needs_resync"] = True
                new_brief["chunk_mapping_confidence"] = "stale"
                cp.brief = new_brief

        # Auto-generate L1 file summaries so roadmap planning & brief backfill
        # can match files by keyword. Best-effort: never fail the whole process.
        try:
            meta = dict(source.meta_data or {})
            ra = dict(meta.get("repo_analysis") or {})
            if (source.type == "github" and ra.get("dir_groups")
                    and not ra.get("file_summaries")
                    and settings.llm_api_key and settings.llm_api_key != "***"):
                summaries = await _generate_file_summaries(db, source)
                if summaries:
                    await _save_file_summaries(db, source, summaries)
                    print(f"[process] auto file_summaries: {len(summaries)} files for source {source.id}")
        except Exception as e:
            print(f"[process] auto file_summaries skipped (source {source.id}): {type(e).__name__}: {e}")

        source.status = "processed"
        await db.commit()
        return {"status": "ok", "chunk_count": len(chunks_data),
                "affected_checkpoints": affected_cp_ids}

    except Exception as e:
        source.status = "failed"
        source.error = str(e)
        await db.commit()
        raise HTTPException(500, f"Source processing failed: {str(e)}")


# ── T6: reference-source cache serving + image captioning ──

@router.get("/sources/{source_id}/files/{file_path:path}")
async def serve_source_file(
    source_id: int,
    file_path: str,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Serve derived reference files (images/markdown), not workspace files."""
    await require_owned_source(db, current.learner.id, source_id)
    base = os.path.realpath(os.path.join(settings.source_cache_dir, str(source_id)))
    full = os.path.realpath(os.path.join(base, file_path))
    if not full.startswith(base + os.sep):
        raise HTTPException(400, "非法路径")
    if not os.path.isfile(full):
        raise HTTPException(404, "文件不存在（可能需要重新处理来源）")
    from fastapi.responses import FileResponse
    return FileResponse(full)


@router.post("/projects/{project_id}/sources/{source_id}/images/caption")
async def start_image_captioning(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
    req: dict = Body(default={}),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Trigger image captioning (T6).

    mode=free (default): md-context + local OCR + SVG structure — zero cost.
    mode=api: Moonshot vision for images flagged needs_api (pure graphics/photos),
    only when API enhancement is enabled in settings (idempotent toggle).
    """
    await require_owned_project(db, current.learner.id, project_id)
    source = await require_owned_source(db, current.learner.id, source_id, project_id)
    if source.type != "github":
        raise HTTPException(400, "仅支持 GitHub 仓库的图片")

    mode = (req or {}).get("mode", "free")
    if mode == "api":
        from app.core.config import settings as _s
        if not (_s.vision_api_enhance):
            raise HTTPException(400, "未开启 API 图片增强：请在设置页开启「允许 API 图片理解」")
        if not (_s.vision_api_key or _s.llm_api_key):
            raise HTTPException(400, "请先配置 VISION_API_KEY（或 LLM_API_KEY）")

    persist_dir = os.path.join(settings.source_cache_dir, str(source_id))
    if not os.path.isdir(persist_dir):
        raise HTTPException(400, "仓库文件缓存不存在，请先重新处理来源")

    from app.services.task_manager import find_running_task, manager
    running = await find_running_task(source_id, "image_caption")
    if running:
        return {"task_id": running.id, "status": running.status, "already_running": True}

    task = Task(
        learner_id=current.learner.id,
        project_id=project_id,
        type="image_caption",
        status="queued",
        payload={"source_id": source_id, "project_id": project_id,
                 "mode": mode, "limit": (req or {}).get("limit")},
        progress={"current": 0, "total": 0, "message": "排队中..."},
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    from app.services.task_runners import run_image_captioning
    manager.submit(task.id, run_image_captioning(task.id))
    return {"task_id": task.id, "status": task.status, "already_running": False}


# ── L1: File Summaries (batch LLM, cached) ──

@router.post("/projects/{project_id}/sources/{source_id}/analyze")
async def analyze_source_structure(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """
    Backfill L0 structure confidence + logic type from existing repo analysis
    (no LLM, no re-chunking — safe for already-processed sources).
    """
    await require_owned_project(db, current.learner.id, project_id)
    source = await require_owned_source(db, current.learner.id, source_id, project_id)

    meta = dict(source.meta_data or {})
    ra = dict(meta.get("repo_analysis") or {})
    if not ra.get("dir_groups"):
        raise HTTPException(400, "该来源没有目录结构，无法分析（请先重新处理来源）")

    confidence = chunker.compute_structure_confidence(ra.get("readme_toc", []), ra.get("dir_groups", []))
    logic = chunker.detect_structure_logic(ra.get("dir_groups", []), ra.get("readme_toc", []))
    ra["structure_confidence"] = confidence
    ra["structure_logic"] = logic
    # CRITICAL: JSON columns are compared with == at flush time. If we mutate
    # the loaded dict in place, the "new" value equals the original → no UPDATE.
    # Always copy on read, then assign a fresh dict.
    source.meta_data = {**meta, "repo_analysis": ra}
    await db.commit()

    return {"status": "ok", "structure_confidence": confidence, "structure_logic": logic}


@router.post("/projects/{project_id}/sources/{source_id}/summarize")
async def summarize_source_files(
    project_id: int,
    source_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """
    Generate one-line summaries per file (L1 of repo understanding).
    Cached in source.meta_data.repo_analysis.file_summaries; idempotent.
    """
    await require_owned_project(db, current.learner.id, project_id)
    source = await require_owned_source(db, current.learner.id, source_id, project_id)

    meta = dict(source.meta_data or {})
    repo_analysis = dict(meta.get("repo_analysis") or {})
    cached = repo_analysis.get("file_summaries")
    if cached:
        return {"status": "ok", "cached": True, "files_count": len(cached), "summaries": cached}

    if source.type != "github" or not repo_analysis.get("dir_groups"):
        raise HTTPException(400, "该来源没有目录结构，无法生成文件摘要（仅支持 GitHub 仓库）")

    # Group chunks by file
    chunk_result = await db.execute(
        select(Chunk).where(Chunk.source_id == source.id).order_by(Chunk.index)
    )
    chunks = chunk_result.scalars().all()
    by_file = {}
    for c in chunks:
        fp = (c.meta_data or {}).get("file", "") or f"chunk-{c.id}"
        by_file.setdefault(fp, []).append(c)

    if not by_file:
        raise HTTPException(400, "该来源没有可读取的切片")

    # API key check
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key: 在设置页填写 LLM_API_KEY")

    summaries = await _generate_file_summaries(db, source)

    if not summaries:
        raise HTTPException(502, "文件摘要生成失败，请重试或检查 LLM 配置")

    await _save_file_summaries(db, source, summaries)

    return {"status": "ok", "cached": False, "files_count": len(summaries), "summaries": summaries}


async def _generate_file_summaries(db: AsyncSession, source) -> dict:
    """L1 repo understanding: one-line summary per file (LLM, batched).
    Returns summaries dict (possibly partial/empty). No DB writes;
    callers decide how to handle empty results.
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    if not settings.llm_api_key or settings.llm_api_key == "***":
        return {}

    chunk_result = await db.execute(
        select(Chunk).where(Chunk.source_id == source.id).order_by(Chunk.index)
    )
    chunks = chunk_result.scalars().all()
    by_file = {}
    for c in chunks:
        fp = (c.meta_data or {}).get("file", "") or f"chunk-{c.id}"
        by_file.setdefault(fp, []).append(c)
    if not by_file:
        return {}

    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.2,
        timeout=60,
        max_retries=0,
    )

    import re as _re, json as _json
    files = sorted(by_file.keys())
    summaries = {}
    BATCH = 40
    for i in range(0, len(files), BATCH):
        batch = files[i:i + BATCH]
        lines = []
        for fp in batch:
            cs = by_file[fp]
            preview = cs[0].content[:150].replace("\n", " ")
            lines.append(f"- {fp} ({len(cs)} 块): {preview}")
        prompt = (
            "你是仓库结构分析器。下面是仓库中一批文件的路径与内容预览。\n"
            "请为每个文件生成一句话中文摘要，说明它在学习资料中的作用。\n"
            f"共 {len(batch)} 个文件：\n" + "\n".join(lines) + "\n\n"
            "输出 JSON：{\"文件路径\": \"一句话摘要\", ...}。只输出 JSON，不要多余文字。"
        )
        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            content = resp.content
            m = _re.search(r"```json\s*(.*?)\s*```", content, _re.DOTALL)
            if m:
                data = _json.loads(m.group(1))
                for k, v in data.items():
                    summaries[k] = str(v)[:120]
            else:
                # Fallback: try to find a bare JSON object
                start = content.find("{")
                end = content.rfind("}")
                if start != -1 and end > start:
                    data = _json.loads(content[start:end + 1])
                    for k, v in data.items():
                        summaries[k] = str(v)[:120]
        except Exception as e:
            print(f"[Summarize] batch {i // BATCH} failed: {e}")

    return summaries


async def _save_file_summaries(db: AsyncSession, source, summaries: dict) -> None:
    """Persist file_summaries into source.meta_data.repo_analysis (idempotent)."""
    if not summaries:
        return
    meta = dict(source.meta_data or {})
    repo_analysis = dict(meta.get("repo_analysis") or {})
    # CRITICAL: JSON columns are compared with == at flush time. If we mutate
    # the loaded dict in place, the "new" value equals the original → no UPDATE.
    # Always copy on read, then assign a fresh dict.
    repo_analysis["file_summaries"] = summaries
    source.meta_data = {**meta, "repo_analysis": repo_analysis}
    await db.commit()


# ── Process All Sources ──

@router.post("/projects/{project_id}/sources/process-all")
async def process_all_sources(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Process all pending sources for a project."""
    await require_owned_project(db, current.learner.id, project_id)
    result = await db.execute(
        select(Source).where(
            Source.project_id == project_id,
            Source.status.in_(["pending", "failed"])
        )
    )
    sources = result.scalars().all()
    if not sources:
        return {"status": "ok", "processed": 0, "message": "No sources to process"}

    count = 0
    errors = []
    for source in sources:
        try:
            source.status = "processing"
            await db.commit()

            affected_cp_ids = (await db.execute(
                select(Checkpoint.id)
                .join(CheckpointChunk).join(Chunk)
                .where(Chunk.source_id == source.id)
                .distinct()
            )).scalars().all()

            persist_dir = os.path.join(settings.source_cache_dir, str(source.id))
            if os.path.exists(persist_dir):
                shutil.rmtree(persist_dir, ignore_errors=True)
            os.makedirs(persist_dir, exist_ok=True)

            # New: returns {chunks, source_meta}
            result_data = await chunker.process_source(source.type, _source_input(source), persist_dir=persist_dir)
            chunks_data = result_data["chunks"]
            source_meta = result_data.get("source_meta", {})
            source_meta["source_cache_dir"] = persist_dir
            source_meta["image_files"] = _count_images(persist_dir)
            if source_meta:
                try:
                    source.meta_data = {**(source.meta_data or {}), "repo_analysis": source_meta}
                except AttributeError:
                    pass

            old = await db.execute(select(Chunk).where(Chunk.source_id == source.id))
            for c in old.scalars().all():
                await db.delete(c)

            for cd in chunks_data:
                chunk = Chunk(
                    source_id=source.id,
                    index=cd["index"],
                    content=cd["content"],
                    tokens=cd["tokens"],
                    meta_data=cd.get("meta", {}),
                )
                db.add(chunk)

            # Mark affected checkpoints' briefs as needing resync (chunk ids changed)
            for cp_id in affected_cp_ids:
                cp = (await db.execute(select(Checkpoint).where(Checkpoint.id == cp_id))).scalar_one_or_none()
                if cp and cp.brief:
                    new_brief = dict(cp.brief)
                    new_brief["needs_resync"] = True
                    new_brief["chunk_mapping_confidence"] = "stale"
                    cp.brief = new_brief

            # Auto-generate L1 file summaries (best-effort, see process_source)
            try:
                meta = dict(source.meta_data or {})
                ra = dict(meta.get("repo_analysis") or {})
                if (source.type == "github" and ra.get("dir_groups")
                        and not ra.get("file_summaries")
                        and settings.llm_api_key and settings.llm_api_key != "***"):
                    summaries = await _generate_file_summaries(db, source)
                    if summaries:
                        await _save_file_summaries(db, source, summaries)
                        print(f"[process-all] auto file_summaries: {len(summaries)} files for source {source.id}")
            except Exception as e:
                print(f"[process-all] auto file_summaries skipped (source {source.id}): {type(e).__name__}: {e}")

            source.status = "processed"
            await db.commit()
            count += 1

        except Exception as e:
            source.status = "failed"
            source.error = str(e)
            await db.commit()
            errors.append({"source_id": source.id, "error": str(e)})

    return {"status": "ok", "processed": count, "errors": errors}


@router.put("/projects/{project_id}/sources/{source_id}/role")
async def set_source_role(
    project_id: int,
    source_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """T10: set source role — main (roadmap skeleton) | auxiliary (retrieval only)."""
    await require_owned_project(db, current.learner.id, project_id)
    source = await require_owned_source(db, current.learner.id, source_id, project_id)
    role = (data or {}).get("role", "main")
    if role not in ("main", "auxiliary"):
        raise HTTPException(400, "role 必须是 main 或 auxiliary")
    source.role = role
    await db.commit()
    return {"status": "ok", "role": role}


# ── T10: reconcile new sources into the roadmap ──

@router.post("/projects/{project_id}/reconcile")
async def reconcile_sources(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """T10: suggest how a new/changed source fits the existing roadmap.

    One LLM call comparing the source's structure (L0/L1) with current
    checkpoints → suggestions: insert new checkpoints, extend existing
    checkpoint scopes, or ignore. Apply happens via /roadmap/reconcile-apply
    after the user confirms.
    """
    await require_owned_project(db, current.learner.id, project_id)
    if not settings.llm_api_key or settings.llm_api_key == "***":
        raise HTTPException(400, "请先配置 API Key")
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )).scalar_one_or_none()
    if not roadmap:
        raise HTTPException(400, "该项目还没有路线图")
    cps = (await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id, Checkpoint.archived == False)  # noqa: E712
        .order_by(Checkpoint.order)
    )).scalars().all()
    sources = (await db.execute(
        select(Source).where(Source.project_id == project_id).order_by(Source.id)
    )).scalars().all()

    # Source structure digest (dir groups + file summaries, main sources only)
    lines = []
    for s in sources:
        ra = (s.meta_data or {}).get("repo_analysis") or {}
        groups = ra.get("dir_groups") or []
        summaries = ra.get("file_summaries") or {}
        lines.append(f"## 来源 #{s.id} ({s.role}, {s.url[:60]})")
        for g in groups[:15]:
            lines.append(f"  📁 {g.get('name')} ({g.get('count')} 文件)")
        for fp, sm in list(summaries.items())[:20]:
            lines.append(f"  - {fp}: {sm}")

    cp_lines = [f"- 关卡{cp.order} {cp.title}: {cp.description or ''}" for cp in cps]
    prompt = (
        "你是学习路线规划专家。现有学习路线如下，新加入/更新了一个参考资料仓库。\n"
        "请判断新仓库与现有路线的契合度，给出整合建议。\n\n"
        "## 现有路线\n" + "\n".join(cp_lines) + "\n\n"
        "## 仓库结构\n" + "\n".join(lines) + "\n\n"
        "## 输出 JSON（只输出 JSON）\n"
        "{\"insert\": [{\"after_order\": 3, \"title\": \"建议关卡名\", "
        "\"description\": \"学习目标\", \"files\": [\"相关文件路径\"]}], "
        "\"extend\": [{\"checkpoint_order\": 2, \"files\": [\"补充文件\"]}], "
        "\"ignore\": true|false, \"reason\": \"一句话理由\"}\n"
        "规则：只输出确有价值的建议；仓库与路线无关时 ignore=true。"
    )
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage
    llm = ChatOpenAI(
        model=settings.llm_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0.3,
        timeout=120,
        max_retries=0,
        max_tokens=4000,
        model_kwargs={"response_format": {"type": "json_object"}},
    )
    try:
        resp = await llm.ainvoke([HumanMessage(content=prompt)])
        import re as _re
        content = resp.content
        m = _re.search(r"```json\s*(.*?)\s*```", content, _re.DOTALL)
        raw = m.group(1) if m else content
        import json as _json
        data = _json.loads(raw)
    except Exception as e:
        raise HTTPException(502, f"建议生成失败: {str(e)[:200]}")

    return {"suggestion": data, "sources": [{"id": s.id, "role": s.role, "url": s.url} for s in sources]}


@router.post("/projects/{project_id}/reconcile/apply")
async def apply_reconcile(
    project_id: int,
    data: dict = Body(default={}),
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """T10: apply confirmed reconcile suggestions (insert checkpoints / extend
    scopes). Deterministic — no LLM here."""
    await require_owned_project(db, current.learner.id, project_id)
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )).scalar_one_or_none()
    if not roadmap:
        raise HTTPException(404, "Roadmap not found")

    all_chunks = (await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id)
    )).scalars().all()
    chunks_by_file = {}
    for c in all_chunks:
        fp = (c.meta_data or {}).get("file", "")
        if fp:
            chunks_by_file.setdefault(fp, []).append(c)

    # Gather structure info for briefs
    sources = (await db.execute(
        select(Source).where(Source.project_id == project_id).order_by(Source.id)
    )).scalars().all()
    structure_logic, structure_confidence = "mixed", "low"
    for s in sources:
        ra = (s.meta_data or {}).get("repo_analysis") or {}
        if ra.get("structure_logic"):
            structure_logic = ra["structure_logic"]
            structure_confidence = (ra.get("structure_confidence") or {}).get("level", "low")
            break
    main_source_id = next((s.id for s in sources if s.role == "main"),
                          (sources[0].id if sources else None))

    # Reindex existing checkpoints after inserts
    cps = (await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
        .order_by(Checkpoint.order)
    )).scalars().all()

    async def _assign_files(cp, files):
        valid = [f for f in files if f in chunks_by_file]
        scope_ids = []
        for f in valid:
            scope_ids += [c.id for c in chunks_by_file[f]]
        scope_ids = list(dict.fromkeys(scope_ids))
        old = (await db.execute(
            select(CheckpointChunk).where(CheckpointChunk.checkpoint_id == cp.id)
        )).scalars().all()
        for cc in old:
            await db.delete(cc)
        for cid in scope_ids:
            db.add(CheckpointChunk(checkpoint_id=cp.id, chunk_id=cid))
        node = {"title": cp.title, "description": cp.description,
                "prerequisites": cp.prerequisites or [], "key_concepts": []}
        cp.brief = _build_brief(cp.id, cp.order, node, valid, scope_ids, [],
                                structure_logic, structure_confidence, main_source_id)

    inserted = extended = 0
    inserts = (data or {}).get("insert") or []
    extends = (data or {}).get("extend") or []

    # Extend first (stable orders), then insert
    for ex in extends:
        target = next((c for c in cps if c.order == ex.get("checkpoint_order")), None)
        if not target or target.archived:
            continue
        old_files = (target.brief or {}).get("scope", {}).get("files") or []
        merged = list(dict.fromkeys(old_files + [f for f in (ex.get("files") or []) if isinstance(f, str)]))
        await _assign_files(target, merged)
        extended += 1

    if inserts:
        existing_ordered = sorted([c for c in cps if not c.archived], key=lambda c: c.order)
        # create new checkpoints (order assigned during re-layout below)
        pending = []
        for ins in inserts:
            cp = Checkpoint(
                roadmap_id=roadmap.id,
                title=ins.get("title", "新关卡"),
                description=ins.get("description", ""),
                prerequisites=[],
                completed=False,
                learning_status="not_started",
                legacy_completed=False,
                learning_contract={
                    "concept_ids": [],
                    "practice_target": {"requires_generation": True},
                    "exit_criteria": ["knowledge_verified", "independent_practice"],
                },
            )
            db.add(cp)
            await db.flush()
            await _assign_files(cp, ins.get("files") or [])
            pending.append((ins.get("after_order"), cp))
            inserted += 1
        # Re-layout: insert each new cp right after its after_order checkpoint
        final = []
        for c in existing_ordered:
            final.append(c)
            for after, cp in pending:
                if after == c.order:
                    final.append(cp)
        used_ids = {id(c) for c in final}
        for after, cp in pending:
            if id(cp) not in used_ids:
                final.append(cp)  # unmatched after_order → append at end
        for i, cp in enumerate(final, start=1):
            cp.order = i

    await db.commit()
    return {"status": "ok", "inserted": inserted, "extended": extended}


# ── Roadmap Agent Chat ──

@router.post("/projects/{project_id}/roadmap/chat", response_model=AgentChatResponse)
async def roadmap_chat(
    project_id: int,
    req: AgentChatRequest,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Chat with the roadmap planning agent."""
    await require_owned_project(db, current.learner.id, project_id)
    if req.require_submission:
        action = await db.get(AgentAction, req.action_id) if req.action_id is not None else None
        if not action or (
            action.learner_id != current.learner.id
            or action.project_id != project_id
            or action.capability != "apply_learning_path"
            or action.status != "running"
        ):
            raise HTTPException(409, "正式路线只能通过已确认的 Tutor Action 写入")
    # Get project info
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(404, "Project not found")

    # Chunks are NOT loaded eagerly (huge repos: 100k+ chunks / 288MB).
    # The agent's list_chunks/read_chunk/search_chunks tools query the DB
    # on demand; passing an empty list keeps the request lightweight.
    chunks_data = []

    # Source metadata (repo analysis + file summaries) for L0/L1 tools
    src_result = await db.execute(
        select(Source).where(Source.project_id == project_id)
    )
    sources = src_result.scalars().all()
    sources_info = []
    for s in sources:
        meta = s.meta_data or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except Exception:
                meta = {}
        sources_info.append({
            "source_id": s.id,
            "type": s.type,
            "url": s.url,
            "role": s.role or "main",
            "repo_analysis": meta.get("repo_analysis") or {},
        })

    planning_context = await _roadmap_planning_context(db, current, project_id)

    # Get existing roadmap (or create placeholder on first chat)
    existing_roadmap = None
    r_result = await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )
    roadmap = r_result.scalar_one_or_none()
    if roadmap:
        existing_roadmap = roadmap.raw_json
    else:
        # Create roadmap placeholder immediately to store conversation
        roadmap = Roadmap(project_id=project_id, raw_json={"checkpoints": []}, conversation_history=[])
        db.add(roadmap)
        await db.commit()
        await db.refresh(roadmap)

    # Merge real completed status from DB into the roadmap nodes (by order)
    if existing_roadmap and roadmap:
        cp_rows = (await db.execute(
            select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
        )).scalars().all()
        completed_by_order = {cp.order: cp.learning_status == "completed" for cp in cp_rows}
        for node in existing_roadmap.get("checkpoints", []):
            node["completed"] = completed_by_order.get(node.get("order"), False)

    # Check if LLM is configured
    if not settings.llm_api_key or settings.llm_api_key in ("", "sk-your-key-here"):
        raise HTTPException(
            400,
            "请先配置 API Key: 复制 .env.example 为 .env，并填入 LLM_API_KEY"
        )

    # Run agent
    try:
        agent = RoadmapAgent()
        result = await agent.chat(
            message=req.message,
            history=[m.model_dump() for m in req.history],
            topic=project.name,
            chunks=chunks_data,
            existing_roadmap=existing_roadmap,
            sources_info=sources_info,
            planning_context=planning_context,
            require_submission=req.require_submission,
        )
    except Exception as e:
        raise HTTPException(502, f"AI Agent error: {str(e)}")

    # A route proposal is not allowed to materialize checkpoints, even if the
    # model called submit_roadmap prematurely.  Only the confirmed Action Board
    # execution above can carry require_submission=True.
    if result["updated_roadmap"] and not req.require_submission:
        result["updated_roadmap"] = None

    # Save conversation history
    if roadmap:
        history = roadmap.conversation_history or []
        history.append({"role": "user", "content": req.message})
        history.append({"role": "assistant", "content": result["message"]})
        # Keep last 50 messages
        roadmap.conversation_history = history[-50:]
        await db.commit()

    # If roadmap was updated, save it
    if result["updated_roadmap"]:
        if not roadmap:
            roadmap = Roadmap(project_id=project_id, raw_json=result["updated_roadmap"])
            db.add(roadmap)
        else:
            roadmap.raw_json = result["updated_roadmap"]
            from datetime import datetime
            roadmap.updated_at = datetime.utcnow()

        await db.commit()

        # Also create/update checkpoint records
        await _sync_checkpoints(db, project_id, result["updated_roadmap"])

    return AgentChatResponse(
        message=result["message"],
        updated_roadmap=result["updated_roadmap"],
    )


@router.get("/projects/{project_id}/roadmap/history")
async def get_roadmap_history(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """Get the persistent conversation history for a project's roadmap."""
    await require_owned_project(db, current.learner.id, project_id)
    result = await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )
    roadmap = result.scalar_one_or_none()
    if not roadmap:
        return {"history": []}
    return {"history": roadmap.conversation_history or []}


def _build_brief(cp_id, order, node, files, scope_ids, seed_ids,
                 structure_logic, structure_confidence, main_source_id) -> dict:
    """Build the CheckpointBrief handoff contract (shared by sync/backfill)."""
    seeds_in_scope = [i for i in seed_ids if i in scope_ids]
    mapping_conf = (
        "high"
        if files and seed_ids and len(seeds_in_scope) == len(seed_ids)
        else "medium"
    )
    return {
        "version": 1,
        "checkpoint_id": cp_id,
        "order": order,
        "title": node.get("title", ""),
        "objective": node.get("description", ""),
        "prerequisites": node.get("prerequisites", []),
        "scope": {
            "main_source_id": main_source_id,
            "files": files,
            "structure_logic": structure_logic,
            "structure_confidence": structure_confidence,
        },
        "seed_chunks": seed_ids,
        "chunk_mapping_confidence": mapping_conf,
        "key_concepts": node.get("key_concepts", []),
        "retrieval_policy": {
            "boost_chunk_ids": seed_ids,
            "boost_weight": 1.5,
            "restrict_to_scope": bool(files),
            "allow_fallback_global": True,
        },
        "practice_plan": {"concept": True, "code": True},
    }


def _match_files_by_keywords(title: str, description: str, summaries: dict) -> list:
    """Deterministic file suggestion: checkpoint title keywords × file summaries.

    Returns up to 8 file paths whose summary/path matches the title tokens.
    """
    import re as _re
    stopwords = {"基础", "入门", "快速", "扫过", "核心", "高级", "技巧", "简单",
                 "实战", "常用", "与", "和", "及", "以及", "的", "中", "从", "到",
                 "于", "and", "the", "of", "with", "for", "in", "on"}
    tokens = set()
    blob = f"{title} {description or ''}"
    # English / numbers / underscores
    tokens |= {t.lower() for t in _re.findall(r"[A-Za-z0-9_]{2,}", blob)}
    # Chinese: 2-4 char substrings of runs (keeps 线性回归, 卷积, 感知机…)
    cjk_runs = _re.findall(r"[\u4e00-\u9fff]{2,}", blob)
    for run in cjk_runs:
        if len(run) <= 4:
            tokens.add(run)
        else:
            tokens.add(run[:2])
            tokens.add(run[:4])
            tokens.add(run[-2:])
            tokens.add(run[-4:])
    tokens -= stopwords
    tokens = {t for t in tokens if len(t) >= 2}
    if not tokens:
        return []

    scored = []
    for fp, sm in summaries.items():
        hay = f"{fp.lower()} {str(sm).lower()}"
        score = 0
        for t in tokens:
            if t in fp.lower():
                score += 2
            elif t in str(sm).lower():
                score += 1
        if score > 0:
            scored.append((score, fp))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [fp for _, fp in scored[:8]]


@router.post("/projects/{project_id}/roadmap/briefs")
async def backfill_briefs(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """
    T3/T4: backfill CheckpointBriefs for existing roadmaps (no LLM).
    File derivation order: existing chunk links → keyword × file-summary
    matching → (fallback) one batched LLM call for checkpoints still empty.
    Also applies the scope assignments (equivalent to /roadmap/resync).
    """
    await require_owned_project(db, current.learner.id, project_id)
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )).scalar_one_or_none()
    if not roadmap:
        raise HTTPException(404, "Roadmap not found")

    all_chunks = (await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id)
    )).scalars().all()
    chunks_by_id = {c.id: c for c in all_chunks}
    chunks_by_file = {}
    for c in all_chunks:
        fp = (c.meta_data or {}).get("file", "")
        if fp:
            chunks_by_file.setdefault(fp, []).append(c)

    sources = (await db.execute(
        select(Source).where(Source.project_id == project_id).order_by(Source.id)
    )).scalars().all()
    structure_logic, structure_confidence = "mixed", "low"
    summaries = {}
    for s in sources:
        ra = (s.meta_data or {}).get("repo_analysis") or {}
        if ra.get("structure_logic"):
            structure_logic = ra["structure_logic"]
            structure_confidence = (ra.get("structure_confidence") or {}).get("level", "low")
        summaries.update(ra.get("file_summaries") or {})
    main_source_id = sources[0].id if sources else None

    cps = (await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id).order_by(Checkpoint.order)
    )).scalars().all()

    # Pass 1: derive files deterministically
    cp_files = {}  # cp.id -> [files]
    for cp in cps:
        cc_ids = (await db.execute(
            select(CheckpointChunk.chunk_id).where(CheckpointChunk.checkpoint_id == cp.id)
        )).scalars().all()
        seed_ids = list(cc_ids)
        files = sorted({(chunks_by_id[i].meta_data or {}).get("file", "") for i in seed_ids
                        if i in chunks_by_id and (chunks_by_id[i].meta_data or {}).get("file")})
        if not files and summaries:
            files = _match_files_by_keywords(cp.title, cp.description or "", summaries)
        cp_files[cp.id] = (seed_ids, files)

    # Pass 2: LLM batch for still-empty checkpoints
    empty = [(cp, cp_files[cp.id][1]) for cp in cps if not cp_files[cp.id][1]]
    if empty and summaries and settings.llm_api_key and settings.llm_api_key != "***":
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import HumanMessage
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.2,
            timeout=90,
            max_retries=0,
        )
        cp_lines = [f"- {cp.title}: {cp.description or ''}" for cp, _ in empty]
        sum_lines = [f"- {fp}: {sm}" for fp, sm in list(summaries.items())[:300]]
        prompt = (
            "你是学习资料组织者。下面是一个学习路线的关卡列表，以及仓库中所有文件的摘要。\n"
            "请为每个关卡选择 2-8 个最相关的文件（只从文件列表中选择，不要编造路径）。\n\n"
            "## 关卡\n" + "\n".join(cp_lines) + "\n\n## 文件\n" + "\n".join(sum_lines) + "\n\n"
            "输出 JSON：{\"关卡标题\": [\"文件路径\", ...], ...}。只输出 JSON。"
        )
        try:
            resp = await llm.ainvoke([HumanMessage(content=prompt)])
            content = resp.content
            import re as _re
            m = _re.search(r"```json\s*(.*?)\s*```", content, _re.DOTALL)
            raw = m.group(1) if m else content
            start, end = raw.find("{"), raw.rfind("}")
            if start != -1 and end > start:
                mapping = json.loads(raw[start:end + 1])
                for cp, _ in empty:
                    picked = [f for f in (mapping.get(cp.title) or []) if f in chunks_by_file]
                    if picked:
                        cp_files[cp.id] = (cp_files[cp.id][0], picked[:8])
        except Exception as e:
            print(f"[backfill_briefs] LLM file mapping failed: {type(e).__name__}: {str(e)[:150]}")

    # Apply: assign chunks by files + write briefs
    updated = assigned = 0
    for cp in cps:
        seed_ids, files = cp_files[cp.id]
        valid_files = [f for f in files if f in chunks_by_file]
        scope_ids = []
        if valid_files:
            for f in valid_files:
                scope_ids += [c.id for c in chunks_by_file[f]]
            scope_ids = list(dict.fromkeys(scope_ids))
        if not scope_ids:
            scope_ids = [i for i in seed_ids if i in chunks_by_id]

        if valid_files and scope_ids:
            old_cc = await db.execute(
                select(CheckpointChunk).where(CheckpointChunk.checkpoint_id == cp.id)
            )
            for cc in old_cc.scalars().all():
                await db.delete(cc)
            for cid in scope_ids:
                db.add(CheckpointChunk(checkpoint_id=cp.id, chunk_id=cid))
            assigned += 1

        node = {"title": cp.title, "description": cp.description,
                "prerequisites": cp.prerequisites or [], "key_concepts": []}
        cp.brief = _build_brief(cp.id, cp.order, node, valid_files, scope_ids, seed_ids,
                                structure_logic, structure_confidence, main_source_id)
        updated += 1
    await db.commit()
    return {"status": "ok", "updated": updated, "assigned": assigned,
            "files_by_checkpoint": {cp.id: cp_files[cp.id][1] for cp in cps}}


@router.post("/projects/{project_id}/roadmap/resync")
async def resync_roadmap_chunks(
    project_id: int,
    db: AsyncSession = Depends(get_db),
    current: CurrentLearner = Depends(get_current_learner),
):
    """
    T3/T4: deterministic re-assignment after source re-processing.
    For each checkpoint with a brief, re-assign chunks by scope.files
    (chunk ids change when a source is re-processed; this repairs links
    without needing the LLM).
    """
    await require_owned_project(db, current.learner.id, project_id)
    roadmap = (await db.execute(
        select(Roadmap).where(Roadmap.project_id == project_id)
    )).scalar_one_or_none()
    if not roadmap:
        raise HTTPException(404, "Roadmap not found")

    all_chunks = (await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id)
    )).scalars().all()
    chunks_by_id = {c.id: c for c in all_chunks}
    chunks_by_file = {}
    for c in all_chunks:
        fp = (c.meta_data or {}).get("file", "")
        if fp:
            chunks_by_file.setdefault(fp, []).append(c)

    cps = (await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id).order_by(Checkpoint.order)
    )).scalars().all()
    resynced = skipped = 0
    for cp in cps:
        brief = cp.brief
        files = (brief or {}).get("scope", {}).get("files") or []
        if not files:
            skipped += 1
            continue
        valid_files = [f for f in files if f in chunks_by_file]
        scope_ids = []
        for f in valid_files:
            scope_ids += [c.id for c in chunks_by_file[f]]
        scope_ids = list(dict.fromkeys(scope_ids))
        if not scope_ids:
            skipped += 1
            continue
        old_cc = await db.execute(
            select(CheckpointChunk).where(CheckpointChunk.checkpoint_id == cp.id)
        )
        for cc in old_cc.scalars().all():
            await db.delete(cc)
        for cid in scope_ids:
            db.add(CheckpointChunk(checkpoint_id=cp.id, chunk_id=cid))
        new_brief = dict(brief)
        new_brief.pop("needs_resync", None)
        seed_ids = [i for i in (brief.get("seed_chunks") or []) if i in scope_ids]
        new_brief["seed_chunks"] = seed_ids
        rp = dict(new_brief.get("retrieval_policy") or {})
        rp["boost_chunk_ids"] = seed_ids
        new_brief["retrieval_policy"] = rp
        new_brief["chunk_mapping_confidence"] = "high" if seed_ids else "medium"
        cp.brief = new_brief
        resynced += 1
    await db.commit()
    return {"status": "ok", "resynced": resynced, "skipped": skipped}


async def _sync_checkpoints(db: AsyncSession, project_id: int, roadmap_data: dict):
    """Sync checkpoint records from roadmap JSON to DB (T2).

    Chunk assignment is scope-based: the agent's "files" decide which chunks
    belong to a checkpoint (deterministic, by file ownership); the agent's
    chunk_ids become "seed_chunks" that boost retrieval downstream. Each
    checkpoint also gets a CheckpointBrief (handoff contract).
    """
    r_result = await db.execute(select(Roadmap).where(Roadmap.project_id == project_id))
    roadmap = r_result.scalar_one_or_none()
    if not roadmap:
        return

    # Load project chunks grouped by file (for scope assignment + briefs)
    all_chunks = (await db.execute(
        select(Chunk).join(Source).where(Source.project_id == project_id)
    )).scalars().all()
    chunks_by_id = {c.id: c for c in all_chunks}
    chunks_by_file = {}
    for c in all_chunks:
        fp = (c.meta_data or {}).get("file", "")
        if fp:
            chunks_by_file.setdefault(fp, []).append(c)

    # Source-level structure info for briefs
    sources = (await db.execute(
        select(Source).where(Source.project_id == project_id).order_by(Source.id)
    )).scalars().all()
    structure_logic, structure_confidence = "mixed", "low"
    for s in sources:
        meta = s.meta_data or {}
        ra = meta.get("repo_analysis") or {}
        if ra.get("structure_logic"):
            structure_logic = ra["structure_logic"]
            structure_confidence = (ra.get("structure_confidence") or {}).get("level", "low")
            break
    main_source_id = sources[0].id if sources else None

    # Get existing checkpoints
    cp_result = await db.execute(
        select(Checkpoint).where(Checkpoint.roadmap_id == roadmap.id)
    )
    existing = {cp.order: cp for cp in cp_result.scalars().all()}

    def _parse_ids(raw_ids) -> list:
        ids = []
        for cid in raw_ids or []:
            if isinstance(cid, str):
                cid = cid.replace("chunk-", "").replace("chunk", "").strip()
            try:
                ids.append(int(cid))
            except (ValueError, TypeError):
                pass
        return ids

    seen_orders = set()
    for node in roadmap_data.get("checkpoints", []):
        order = node["order"]
        seen_orders.add(order)

        if order in existing:
            cp = existing[order]
            cp.title = node.get("title", cp.title)
            cp.description = node.get("description", cp.description)
            cp.prerequisites = node.get("prerequisites", [])
            cp.learning_contract = {
                **dict(cp.learning_contract or {}),
                "concept_ids": node.get("concept_ids") or node.get("key_concepts") or [],
                "knowledge_target": node.get("knowledge_target") or {"checkpoint_id": cp.id},
                "practice_target": node.get("practice_target") or {"requires_generation": True},
                "evidence_target": node.get("evidence_target") or {},
                "exit_criteria": node.get("exit_criteria") or ["knowledge_verified", "independent_practice"],
                "estimated_effort": node.get("estimated_effort", ""),
            }
        else:
            cp = Checkpoint(
                roadmap_id=roadmap.id,
                title=node.get("title", ""),
                description=node.get("description", ""),
                order=order,
                prerequisites=node.get("prerequisites", []),
                completed=False,
                learning_status="not_started",
                legacy_completed=False,
            )
            db.add(cp)
            await db.flush()
            cp.learning_contract = {
                "concept_ids": node.get("concept_ids") or node.get("key_concepts") or [],
                "knowledge_target": node.get("knowledge_target") or {"checkpoint_id": cp.id},
                "practice_target": node.get("practice_target") or {"requires_generation": True},
                "evidence_target": node.get("evidence_target") or {},
                "exit_criteria": node.get("exit_criteria") or ["knowledge_verified", "independent_practice"],
                "estimated_effort": node.get("estimated_effort", ""),
            }

        # ── Scope-based chunk assignment ──
        seed_ids = _parse_ids(node.get("chunk_ids"))
        files = [f for f in (node.get("files") or []) if isinstance(f, str) and f in chunks_by_file]
        scope_ids = []
        if files:
            for f in files:
                scope_ids += [c.id for c in chunks_by_file[f]]
            scope_ids = list(dict.fromkeys(scope_ids))
        if not scope_ids:
            # Fallback: seed chunks only
            scope_ids = [i for i in seed_ids if i in chunks_by_id]

        # Remove old assignments, add scope assignments
        old_cc = await db.execute(
            select(CheckpointChunk).where(CheckpointChunk.checkpoint_id == cp.id)
        )
        for cc in old_cc.scalars().all():
            await db.delete(cc)
        for cid in scope_ids:
            db.add(CheckpointChunk(checkpoint_id=cp.id, chunk_id=cid))

        cp.brief = _build_brief(
            cp.id, order, node, files, scope_ids, seed_ids,
            structure_logic, structure_confidence, main_source_id,
        )

    # Remove checkpoints that are no longer in the roadmap (completed are kept)
    for order, cp in existing.items():
        if order not in seen_orders and not (cp.completed or cp.legacy_completed):
            await db.delete(cp)

    # T10: apply archives — completed checkpoints declared in "archives" are
    # archived (products kept, hidden from the roadmap) instead of deleted
    archives = roadmap_data.get("archives") or []
    for a in archives:
        cp = next((c for c in existing.values()
                   if c.title == a.get("title") and (c.completed or c.legacy_completed)), None)
        if cp and not cp.archived:
            cp.archived = True
            brief = dict(cp.brief or {})
            brief["archived_by"] = a.get("replaced_by_title", "")
            cp.brief = brief

    await db.commit()
