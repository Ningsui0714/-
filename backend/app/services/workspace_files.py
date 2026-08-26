from __future__ import annotations

import difflib
import hashlib
import json
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import shutil
import stat
import tempfile
from typing import Iterable

from sqlalchemy import select

from app.models.project import (
    Checkpoint, Exercise, Lecture, Project, ProjectWorkspace, Roadmap,
)


DESCRIPTOR_SCHEMA = "learnflow.workspace.v1"
MAX_TEXT_BYTES = 2 * 1024 * 1024
INTERNAL_DIR = ".learnflow"
ALWAYS_PROTECTED = {".git", INTERNAL_DIR}
AGENT_SECRET_NAMES = {
    ".env", ".env.local", ".env.production", "credentials", "credentials.json",
    "id_rsa", "id_ed25519",
}
AGENT_SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


class WorkspaceError(Exception):
    def __init__(self, status_code: int, detail: str, code: str = "workspace_error"):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_link_or_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        info = path.stat(follow_symlinks=False)
    except (FileNotFoundError, OSError):
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(reparse_flag and getattr(info, "st_file_attributes", 0) & reparse_flag)


def canonical_root(raw_path: str, *, create: bool = False) -> Path:
    if not raw_path or "\x00" in raw_path:
        raise WorkspaceError(400, "项目目录无效", "invalid_root")
    expanded = Path(raw_path).expanduser()
    if not expanded.is_absolute() or PureWindowsPath(raw_path).drive and os.name != "nt":
        raise WorkspaceError(400, "项目目录必须是本机绝对路径", "invalid_root")
    if os.path.lexists(expanded) and _is_link_or_reparse(expanded):
        raise WorkspaceError(400, "项目目录不能是符号链接或重解析点", "unsafe_link")
    if not expanded.exists():
        if not create:
            raise WorkspaceError(404, "所选项目目录不存在", "root_missing")
        parent = expanded.parent
        if not parent.exists() or not parent.is_dir() or _is_link_or_reparse(parent):
            raise WorkspaceError(400, "项目目录的父目录无效", "invalid_parent")
        expanded.mkdir()
    if not expanded.is_dir():
        raise WorkspaceError(400, "所选路径不是目录", "invalid_root")
    resolved = expanded.resolve(strict=True)
    if _is_link_or_reparse(resolved):
        raise WorkspaceError(400, "项目目录不能是符号链接或重解析点", "unsafe_link")
    return resolved


def normalize_relative_path(raw_path: str) -> str:
    if not raw_path or "\x00" in raw_path:
        raise WorkspaceError(400, "文件路径不能为空", "invalid_path")
    if raw_path.startswith(("/", "\\")) or PureWindowsPath(raw_path).is_absolute():
        raise WorkspaceError(400, "文件路径必须相对于项目目录", "absolute_path")
    normalized = raw_path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", normalized):
        raise WorkspaceError(400, "文件路径不能包含盘符", "absolute_path")
    parts = PurePosixPath(normalized).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise WorkspaceError(400, "文件路径包含不安全的路径段", "path_traversal")
    return "/".join(parts)


def _forbidden_for_agent(relative_path: str) -> bool:
    parts = PurePosixPath(relative_path).parts
    names = {part.casefold() for part in parts}
    basename = parts[-1].casefold()
    return (
        bool(names & ALWAYS_PROTECTED)
        or basename in AGENT_SECRET_NAMES
        or basename.startswith(".env.")
        or any(basename.endswith(suffix) for suffix in AGENT_SECRET_SUFFIXES)
    )


def resolve_workspace_path(
    root: Path,
    raw_path: str,
    *,
    actor: str = "user",
    allow_missing_leaf: bool = False,
) -> tuple[str, Path]:
    relative = normalize_relative_path(raw_path)
    parts = PurePosixPath(relative).parts
    if any(part.casefold() in ALWAYS_PROTECTED for part in parts):
        raise WorkspaceError(403, "该路径由 LearnFlow 或版本控制系统保护", "protected_path")
    if actor == "agent" and _forbidden_for_agent(relative):
        raise WorkspaceError(403, "Agent 无权访问密钥、环境或受保护文件", "agent_path_denied")

    root = canonical_root(str(root))
    candidate = root.joinpath(*parts)
    current = root
    for index, part in enumerate(parts):
        current = current / part
        exists = os.path.lexists(current)
        if exists and _is_link_or_reparse(current):
            raise WorkspaceError(403, "路径包含符号链接或重解析点", "unsafe_link")
        if not exists and (index < len(parts) - 1 or not allow_missing_leaf):
            raise WorkspaceError(404, "文件或目录不存在", "path_missing")

    check_target = candidate if candidate.exists() else candidate.parent
    resolved_check = check_target.resolve(strict=True)
    try:
        if os.path.commonpath([str(root), str(resolved_check)]) != str(root):
            raise WorkspaceError(403, "文件路径越出项目目录", "path_escape")
    except ValueError as exc:
        raise WorkspaceError(403, "文件路径越出项目目录", "path_escape") from exc
    return relative, candidate


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(prefix=".learnflow-write-", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


def _write_json(path: Path, payload: dict) -> None:
    _atomic_write(
        path,
        (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _summary_digest(payload: object) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(raw.encode("utf-8"))


def initialize_managed_layout(
    root: Path,
    project: Project,
    checkpoints: Iterable[Checkpoint],
    lectures: Iterable[Lecture],
    exercises: Iterable[Exercise],
) -> None:
    managed = root / INTERNAL_DIR
    if os.path.lexists(managed) and _is_link_or_reparse(managed):
        raise WorkspaceError(409, ".learnflow 不能是符号链接或重解析点", "unsafe_managed_dir")
    marker = managed / "project.lfproject"
    if marker.exists():
        try:
            existing = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkspaceError(409, "已有 .learnflow/project.lfproject 无法验证", "invalid_marker") from exc
        if int(existing.get("project_id", -1)) != project.id:
            raise WorkspaceError(409, "该目录已经关联另一个 LearnFlow 项目", "workspace_collision")

    for name in ("checkpoints", "history", "trash"):
        (managed / name).mkdir(parents=True, exist_ok=True)
    _write_json(marker, {
        "schema": DESCRIPTOR_SCHEMA,
        "project_id": project.id,
        "name": project.name,
        "summary": project.description or "",
    })

    lecture_by_checkpoint = {item.checkpoint_id: item for item in lectures}
    exercise_by_checkpoint: dict[int, list[Exercise]] = {}
    for exercise in exercises:
        exercise_by_checkpoint.setdefault(exercise.checkpoint_id, []).append(exercise)
    for checkpoint in checkpoints:
        checkpoint_root = managed / "checkpoints" / f"cp-{checkpoint.id}"
        lecture_dir = checkpoint_root / "lectures"
        exercise_dir = checkpoint_root / "exercises"
        lecture_dir.mkdir(parents=True, exist_ok=True)
        exercise_dir.mkdir(parents=True, exist_ok=True)
        lecture = lecture_by_checkpoint.get(checkpoint.id)
        expected_lecture = f"lecture-{lecture.id}.lflecture" if lecture else None
        for stale in lecture_dir.glob("*.lflecture"):
            if stale.name != expected_lecture:
                stale.unlink(missing_ok=True)
        if lecture:
            _write_json(lecture_dir / f"lecture-{lecture.id}.lflecture", {
                "schema": "learnflow.lecture-ref.v1",
                "project_id": project.id,
                "checkpoint_id": checkpoint.id,
                "lecture_id": lecture.id,
                "version": int(lecture.version or 1),
                "summary": checkpoint.title,
                "digest": _summary_digest(lecture.sections or []),
            })
        expected_exercises = {
            f"exercise-{item.id}.lfexercise"
            for item in exercise_by_checkpoint.get(checkpoint.id, [])
        }
        for stale in exercise_dir.glob("*.lfexercise"):
            if stale.name not in expected_exercises:
                stale.unlink(missing_ok=True)
        for exercise in exercise_by_checkpoint.get(checkpoint.id, []):
            protected = {
                "description": exercise.description or "",
                "test_cases": exercise.test_cases or [],
                "judge_mode": exercise.judge_mode,
                "judge_config": exercise.judge_config or {},
            }
            _write_json(exercise_dir / f"exercise-{exercise.id}.lfexercise", {
                "schema": "learnflow.exercise-ref.v1",
                "project_id": project.id,
                "checkpoint_id": checkpoint.id,
                "exercise_id": exercise.id,
                "version": 1,
                "summary": exercise.title,
                "protected_digest": _summary_digest(protected),
            })


async def sync_managed_layout_for_project(db, project_id: int) -> bool:
    """Refresh managed lecture/exercise descriptors for a linked workspace.

    The database remains authoritative. A missing or temporarily unavailable
    workspace must not make saving a lecture or exercise fail.
    """
    workspace = (await db.execute(
        select(ProjectWorkspace).where(ProjectWorkspace.project_id == project_id)
    )).scalar_one_or_none()
    if not workspace or workspace.status != "linked":
        return False
    project = await db.get(Project, project_id)
    if not project:
        return False
    checkpoints = list((await db.execute(
        select(Checkpoint)
        .join(Roadmap, Roadmap.id == Checkpoint.roadmap_id)
        .where(Roadmap.project_id == project_id)
    )).scalars().all())
    if not checkpoints:
        return False
    checkpoint_ids = [item.id for item in checkpoints]
    lectures = list((await db.execute(
        select(Lecture).where(Lecture.checkpoint_id.in_(checkpoint_ids))
    )).scalars().all())
    exercises = list((await db.execute(
        select(Exercise).where(Exercise.checkpoint_id.in_(checkpoint_ids))
    )).scalars().all())
    try:
        root = canonical_root(workspace.root_path, create=False)
        initialize_managed_layout(root, project, checkpoints, lectures, exercises)
    except (OSError, WorkspaceError):
        return False
    return True


def classify_path(path: Path) -> tuple[str, int]:
    size = path.stat().st_size
    if size > MAX_TEXT_BYTES:
        return "workspace_binary", size
    sample = path.read_bytes()
    if b"\x00" in sample:
        return "workspace_binary", size
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return "workspace_binary", size
    return "workspace_text", size


def read_workspace_file(root: Path, raw_path: str, *, actor: str = "user") -> dict:
    relative, path = resolve_workspace_path(root, raw_path, actor=actor)
    if not path.is_file():
        raise WorkspaceError(400, "目标不是普通文件", "not_a_file")
    kind, size = classify_path(path)
    info = path.stat()
    return {
        "path": relative,
        "kind": kind,
        "content": path.read_text(encoding="utf-8") if kind == "workspace_text" else None,
        "sha256": sha256_file(path),
        "size": size,
        "modified_at": info.st_mtime,
        "read_only": False,
    }


def scan_workspace_tree(root: Path) -> list[dict]:
    root = canonical_root(str(root))

    def visit(directory: Path, prefix: str = "") -> list[dict]:
        nodes: list[dict] = []
        try:
            entries = sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold()))
        except OSError as exc:
            raise WorkspaceError(403, "无法读取项目目录", "directory_unreadable") from exc
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            if entry.name == INTERNAL_DIR:
                # Managed implementation details are projected separately as
                # learning artifacts and never exposed in the ordinary tree.
                continue
            try:
                info = entry.stat(follow_symlinks=False)
            except OSError:
                nodes.append({
                    "name": entry.name, "path": relative, "kind": "protected",
                    "protected_reason": "unreadable",
                })
                continue
            if entry.name.casefold() in ALWAYS_PROTECTED or _is_link_or_reparse(entry):
                nodes.append({
                    "name": entry.name, "path": relative, "kind": "protected",
                    "is_directory": entry.is_dir(), "modified_at": info.st_mtime,
                    "protected_reason": "managed" if entry.name == INTERNAL_DIR else "link_or_system",
                })
            elif entry.is_dir():
                nodes.append({
                    "name": entry.name, "path": relative, "kind": "workspace_text",
                    "is_directory": True, "modified_at": info.st_mtime,
                    "children": visit(entry, relative),
                })
            elif entry.is_file():
                kind, size = classify_path(entry)
                nodes.append({
                    "name": entry.name, "path": relative, "kind": kind,
                    "is_directory": False, "size": size, "modified_at": info.st_mtime,
                })
            else:
                nodes.append({
                    "name": entry.name, "path": relative, "kind": "protected",
                    "protected_reason": "unsupported_file_type", "modified_at": info.st_mtime,
                })
        return nodes

    return visit(root)


def build_write_preview(root: Path, raw_path: str, content: str, *, actor: str) -> dict:
    raw = content.encode("utf-8")
    if len(raw) > MAX_TEXT_BYTES:
        raise WorkspaceError(413, "文本文件不能超过 2 MB", "file_too_large")
    relative, path = resolve_workspace_path(root, raw_path, actor=actor, allow_missing_leaf=True)
    if path.exists() and not path.is_file():
        raise WorkspaceError(400, "写入目标不是普通文件", "not_a_file")
    previous = ""
    if path.exists():
        kind, _ = classify_path(path)
        if kind != "workspace_text":
            raise WorkspaceError(415, "二进制或大型文件不能在编辑器中修改", "binary_write_denied")
        previous = path.read_text(encoding="utf-8")
    diff = "".join(difflib.unified_diff(
        previous.splitlines(keepends=True), content.splitlines(keepends=True),
        fromfile=f"a/{relative}", tofile=f"b/{relative}",
    ))
    return {
        "relative_path": relative,
        "path": path,
        "content": content,
        "diff": diff,
        "new_hash": sha256_bytes(raw),
        "exists": path.exists(),
    }


def validate_base_hash(path: Path, base_hash: str | None) -> None:
    if not path.exists():
        if base_hash:
            raise WorkspaceError(409, "文件已被删除，旧提案失效", "hash_conflict")
        return
    if not path.is_file():
        return
    if not base_hash or sha256_file(path) != base_hash:
        raise WorkspaceError(409, "文件已变化，请重新生成修改提案", "hash_conflict")


def snapshot_existing(root: Path, operation_id: int, relative: str, path: Path) -> str | None:
    if not path.exists():
        return None
    snapshot = root / INTERNAL_DIR / "history" / f"op-{operation_id}" / Path(*PurePosixPath(relative).parts)
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    if path.is_dir():
        shutil.copytree(path, snapshot)
    else:
        shutil.copy2(path, snapshot)
    return snapshot.relative_to(root).as_posix()


def apply_operation(root: Path, operation_id: int, operation: str, payload: dict) -> dict:
    actor = payload.get("actor", "agent")
    target_relative, target = resolve_workspace_path(
        root, payload["target_path"], actor=actor,
        allow_missing_leaf=operation in {"create", "write", "mkdir", "restore"},
    )
    destination_relative = None
    destination = None
    if payload.get("destination_path"):
        destination_relative, destination = resolve_workspace_path(
            root, payload["destination_path"], actor=actor, allow_missing_leaf=True,
        )

    if operation in {"create", "write"}:
        preview = build_write_preview(root, target_relative, payload.get("content") or "", actor=actor)
        validate_base_hash(target, payload.get("base_hash"))
        history_path = snapshot_existing(root, operation_id, target_relative, target)
        _atomic_write(target, preview["content"].encode("utf-8"))
        return {
            "path": target_relative, "sha256": preview["new_hash"],
            "history_path": history_path,
        }
    if operation == "mkdir":
        if target.exists():
            raise WorkspaceError(409, "目录已存在", "target_exists")
        target.mkdir()
        return {"path": target_relative, "created": True}
    if operation in {"rename", "move"}:
        if destination is None or destination_relative is None:
            raise WorkspaceError(400, "重命名或移动必须指定目标路径", "destination_required")
        if destination.exists():
            raise WorkspaceError(409, "目标路径已存在", "target_exists")
        destination.parent.mkdir(parents=True, exist_ok=True)
        target.replace(destination)
        return {"path": destination_relative, "previous_path": target_relative}
    if operation == "delete":
        trash = root / INTERNAL_DIR / "trash" / f"op-{operation_id}" / Path(*PurePosixPath(target_relative).parts)
        trash.parent.mkdir(parents=True, exist_ok=True)
        target.replace(trash)
        return {
            "path": target_relative,
            "trash_path": trash.relative_to(root).as_posix(),
            "restorable": True,
        }
    if operation == "restore":
        source = Path(payload.get("restore_source", ""))
        if not source.is_absolute():
            source = root / source
        managed_trash = (root / INTERNAL_DIR / "trash").resolve(strict=True)
        if not source.exists() or _is_link_or_reparse(source):
            raise WorkspaceError(404, "回收站项目不存在", "trash_missing")
        if os.path.commonpath([str(managed_trash), str(source.resolve(strict=True))]) != str(managed_trash):
            raise WorkspaceError(403, "恢复来源不属于工作区回收站", "invalid_restore_source")
        if target.exists():
            raise WorkspaceError(409, "原路径已被占用，不能恢复", "target_exists")
        target.parent.mkdir(parents=True, exist_ok=True)
        source.replace(target)
        return {"path": target_relative, "restored": True}
    raise WorkspaceError(400, "不支持的文件操作", "unsupported_operation")
