from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import datetime
import difflib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import signal
import stat
import subprocess
import tempfile
from typing import Protocol

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.database import async_session
from app.models.learning import AgentAction
from app.models.project import (
    LocalAgentProfile, LocalAgentRun, LocalAgentRunEvent, ProjectWorkspace,
    WorkspaceOperation,
)
from app.services.learning_runtime import record_event
from app.services.workspace_files import (
    AGENT_SECRET_NAMES, AGENT_SECRET_SUFFIXES, MAX_TEXT_BYTES, WorkspaceError,
    _atomic_write, _is_link_or_reparse, apply_operation, canonical_root,
    resolve_workspace_path, sha256_bytes, sha256_file,
)


ALLOWED_ADAPTERS = {"codex_cli", "deterministic_fake"}
ALLOWED_TASK_TYPES = {"code_change", "bug_fix", "refactor", "test", "documentation"}
EXCLUDED_DIRECTORIES = {
    ".git", ".learnflow", ".cache", ".idea", ".vscode", ".venv", "venv",
    ".aws", ".ssh", ".gnupg", ".codex", ".config", "__pycache__",
    "node_modules", "dist", "build", "coverage", "target",
}
MAX_COPY_BYTES = 20 * 1024 * 1024
MAX_DIFF_BYTES = 2 * 1024 * 1024

_tasks: dict[int, asyncio.Task] = {}
_processes: dict[int, asyncio.subprocess.Process] = {}
_event_locks: dict[int, asyncio.Lock] = {}
_event_sequences: dict[int, int] = {}


class LocalAgentError(Exception):
    def __init__(self, status_code: int, detail: str, code: str = "local_agent_error"):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail
        self.code = code


class LocalAgentAdapter(Protocol):
    async def probe(self, profile: LocalAgentProfile) -> dict: ...
    async def start(
        self, profile: LocalAgentProfile, workspace: Path, prompt: str,
    ) -> asyncio.subprocess.Process | None: ...
    def parse_event(self, raw_line: str) -> dict: ...
    async def cancel(self, process: asyncio.subprocess.Process | None) -> None: ...
    def collect_result(self, events: list[dict], return_code: int) -> dict: ...


def _safe_executable(profile: LocalAgentProfile) -> Path:
    raw = (profile.executable_path or "").strip()
    located = shutil.which(raw or "codex")
    candidate = Path(located or raw).expanduser() if (located or raw) else None
    if not candidate or not candidate.is_absolute() or not candidate.exists() or not candidate.is_file():
        raise LocalAgentError(409, "找不到已配置的 Codex CLI 可执行文件", "agent_not_installed")
    resolved = candidate.resolve(strict=True)
    if not os.access(resolved, os.X_OK):
        raise LocalAgentError(409, "Codex CLI 文件不可执行", "agent_not_executable")
    return resolved


def _subprocess_environment() -> dict[str, str]:
    # Deliberately do not pass API keys or arbitrary backend environment data.
    allowed = {
        "PATH", "HOME", "USER", "LOGNAME", "TMPDIR", "TEMP", "TMP",
        "LANG", "LC_ALL", "TERM", "SYSTEMROOT", "WINDIR", "APPDATA", "LOCALAPPDATA",
        "CODEX_HOME",
    }
    return {key: value for key, value in os.environ.items() if key in allowed and value}


class CodexCliAdapter:
    async def probe(self, profile: LocalAgentProfile) -> dict:
        try:
            executable = _safe_executable(profile)
            version = await asyncio.create_subprocess_exec(
                str(executable), "--version", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=_subprocess_environment(),
            )
            stdout, stderr = await asyncio.wait_for(version.communicate(), timeout=10)
            login = await asyncio.create_subprocess_exec(
                str(executable), "login", "status", stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE, env=_subprocess_environment(),
            )
            login_out, login_err = await asyncio.wait_for(login.communicate(), timeout=10)
            login_text = (login_out + login_err).decode("utf-8", errors="replace")[:500]
            return {
                "available": version.returncode == 0,
                "authenticated": login.returncode == 0,
                "version": stdout.decode("utf-8", errors="replace").strip()[:200],
                "message": login_text.strip(),
                "sandbox_policy": "workspace_write",
                "network_policy": "unmanaged",
                "network_boundary_enforced": False,
                "probed_at": datetime.utcnow().isoformat(),
            }
        except (LocalAgentError, OSError, asyncio.TimeoutError) as exc:
            return {
                "available": False, "authenticated": False,
                "message": str(exc)[:300], "network_policy": "unmanaged",
                "network_boundary_enforced": False,
                "probed_at": datetime.utcnow().isoformat(),
            }

    async def start(
        self, profile: LocalAgentProfile, workspace: Path, prompt: str,
    ) -> asyncio.subprocess.Process:
        executable = _safe_executable(profile)
        process_options = (
            {"start_new_session": True}
            if os.name != "nt"
            else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
        )
        process = await asyncio.create_subprocess_exec(
            str(executable), "exec", "--json", "--sandbox", "workspace-write",
            "-C", str(workspace), "-",
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=_subprocess_environment(),
            **process_options,
        )
        assert process.stdin is not None
        process.stdin.write(prompt.encode("utf-8"))
        await process.stdin.drain()
        process.stdin.close()
        return process

    def parse_event(self, raw_line: str) -> dict:
        try:
            payload = json.loads(raw_line)
        except json.JSONDecodeError:
            return {"type": "output", "text": raw_line[:4000]}
        source_type = str(payload.get("type") or "event")
        item = payload.get("item") if isinstance(payload.get("item"), dict) else {}
        normalized = {
            "type": source_type,
            "source_type": source_type,
            "item_type": item.get("type"),
        }
        for key in ("message", "error", "usage"):
            if key in payload:
                normalized[key] = payload[key]
        if item:
            for key in ("id", "command", "status", "exit_code", "text", "path"):
                if key in item:
                    normalized[key] = item[key]
        return normalized

    async def cancel(self, process: asyncio.subprocess.Process | None) -> None:
        if not process or process.returncode is not None:
            return
        if os.name != "nt":
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                return
        else:
            killer = await asyncio.create_subprocess_exec(
                "taskkill", "/PID", str(process.pid), "/T", "/F",
                stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            )
            await killer.wait()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except asyncio.TimeoutError:
            if os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                process.kill()

    def collect_result(self, events: list[dict], return_code: int) -> dict:
        errors = [event for event in events if "fail" in str(event.get("type", ""))]
        tests = [event for event in events if "test" in json.dumps(event, ensure_ascii=False).casefold()]
        return {
            "return_code": return_code,
            "summary": "本地代码 Agent 已完成。" if return_code == 0 else "本地代码 Agent 异常退出。",
            "tests": tests[-20:],
            "risks": errors[-20:],
        }


class DeterministicFakeAdapter:
    async def probe(self, profile: LocalAgentProfile) -> dict:
        return {
            "available": True, "authenticated": True, "version": "seeded-demo-v1",
            "sandbox_policy": "workspace_write", "network_policy": "managed_off",
            "network_boundary_enforced": True, "probed_at": datetime.utcnow().isoformat(),
        }

    async def start(
        self, profile: LocalAgentProfile, workspace: Path, prompt: str,
    ) -> None:
        return None

    def parse_event(self, raw_line: str) -> dict:
        return json.loads(raw_line)

    async def cancel(self, process: asyncio.subprocess.Process | None) -> None:
        return None

    def collect_result(self, events: list[dict], return_code: int) -> dict:
        return {
            "return_code": 0, "summary": "离线演示 Agent 已生成固定修改。",
            "tests": [{"name": "seeded-check", "status": "passed"}], "risks": [],
        }


ADAPTERS: dict[str, LocalAgentAdapter] = {
    "codex_cli": CodexCliAdapter(),
    "deterministic_fake": DeterministicFakeAdapter(),
}


def adapter_for(profile: LocalAgentProfile) -> LocalAgentAdapter:
    adapter = ADAPTERS.get(profile.adapter)
    if not adapter:
        raise LocalAgentError(400, "不支持的本地 Agent 适配器", "adapter_unsupported")
    return adapter


def _is_secret(relative: str) -> bool:
    name = PurePosixPath(relative).name.casefold()
    return (
        name in AGENT_SECRET_NAMES or name in {".envrc", ".netrc", ".npmrc", ".pypirc"}
        or name.startswith(".env.")
        or any(name.endswith(suffix) for suffix in AGENT_SECRET_SUFFIXES)
    )


def _is_managed_learning_descriptor(relative: str) -> bool:
    name = PurePosixPath(relative).name.casefold()
    return name.endswith((".lflecture", ".lfexercise", ".lfproject"))


def _is_reparse(info: os.stat_result) -> bool:
    flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(flag and getattr(info, "st_file_attributes", 0) & flag)


def _iter_safe_source_files(root: Path):
    for directory, names, files in os.walk(root, topdown=True, followlinks=False):
        current = Path(directory)
        safe_names = []
        for name in names:
            child = current / name
            relative = child.relative_to(root).as_posix()
            try:
                info = child.stat(follow_symlinks=False)
            except OSError:
                continue
            if (
                name.casefold() in EXCLUDED_DIRECTORIES or _is_secret(relative)
                or child.is_symlink() or _is_reparse(info)
            ):
                continue
            safe_names.append(name)
        names[:] = safe_names
        for name in files:
            source = current / name
            relative = source.relative_to(root).as_posix()
            try:
                info = source.stat(follow_symlinks=False)
            except OSError:
                continue
            if (
                _is_secret(relative) or _is_managed_learning_descriptor(relative)
                or source.is_symlink() or _is_reparse(info)
                or not source.is_file() or info.st_size > MAX_COPY_BYTES
            ):
                continue
            yield relative, source


def _copy_safe_snapshot(source_root: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for relative, source in _iter_safe_source_files(source_root):
        target = destination.joinpath(*PurePosixPath(relative).parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target, follow_symlinks=False)


async def _run_command(*args: str, cwd: Path | None = None, timeout: int = 60) -> tuple[int, str]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args, cwd=str(cwd) if cwd else None, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT, env=_subprocess_environment(),
        )
        output, _ = await asyncio.wait_for(process.communicate(), timeout=timeout)
        return process.returncode or 0, output.decode("utf-8", errors="replace")[:4000]
    except (OSError, asyncio.TimeoutError) as exc:
        return 1, str(exc)


async def _prepare_isolation(root: Path, run_id: int) -> tuple[Path, Path, dict]:
    parent = Path(settings.local_agent_runs_dir).expanduser() if settings.local_agent_runs_dir else None
    if parent:
        parent.mkdir(parents=True, exist_ok=True)
        isolation = Path(tempfile.mkdtemp(prefix=f"run-{run_id}-", dir=parent))
    else:
        isolation = Path(tempfile.mkdtemp(prefix=f"learnflow-agent-{run_id}-"))
    base = isolation / "base"
    worktree = isolation / "worktree"
    _copy_safe_snapshot(root, base)

    cloned = False
    if (root / ".git").is_dir() and shutil.which("git"):
        return_code, _ = await _run_command(
            shutil.which("git") or "git", "clone", "--no-hardlinks", "--no-local",
            str(root), str(worktree), timeout=120,
        )
        cloned = return_code == 0
    if not cloned:
        worktree.mkdir(parents=True, exist_ok=True)
    # The working tree always reflects the current disk snapshot, including dirty files.
    for child in list(worktree.iterdir()):
        if child.name == ".git":
            continue
        if child.is_dir() and not child.is_symlink():
            shutil.rmtree(child)
        else:
            child.unlink(missing_ok=True)
    _copy_safe_snapshot(root, worktree)
    if shutil.which("git"):
        git = shutil.which("git") or "git"
        if not (worktree / ".git").exists():
            await _run_command(git, "init", cwd=worktree)
        await _run_command(git, "-c", "user.name=LearnFlow Broker", "-c", "user.email=broker@localhost", "add", "-A", cwd=worktree)
        await _run_command(
            git, "-c", "user.name=LearnFlow Broker", "-c", "user.email=broker@localhost",
            "commit", "--allow-empty", "-m", "LearnFlow isolated baseline", cwd=worktree,
        )
    manifest = _snapshot_manifest(base)
    return isolation, worktree, manifest


def _snapshot_manifest(root: Path) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for relative, path in _iter_safe_source_files(root):
        size = path.stat().st_size
        raw = path.read_bytes()
        is_text = size <= MAX_TEXT_BYTES and b"\x00" not in raw
        if is_text:
            try:
                raw.decode("utf-8")
            except UnicodeDecodeError:
                is_text = False
        result[relative] = {
            "sha256": sha256_bytes(raw), "size": size, "is_text": is_text,
        }
    return result


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    if len(raw) > MAX_TEXT_BYTES or b"\x00" in raw:
        raise LocalAgentError(409, "本地 Agent 只能回写 2 MB 内的 UTF-8 文本", "unsupported_change")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise LocalAgentError(409, "本地 Agent 产生了非 UTF-8 文件", "unsupported_change") from exc


def _collect_changes(base: Path, worktree: Path) -> tuple[list[dict], str, list[dict]]:
    baseline = _snapshot_manifest(base)
    current = _snapshot_manifest(worktree)
    changed: list[dict] = []
    risks: list[dict] = []
    deleted = {path for path in baseline if path not in current}
    created = {path for path in current if path not in baseline}

    # Detect exact-content renames/moves so the UI can require a dedicated confirmation.
    paired_created: set[str] = set()
    paired_deleted: set[str] = set()
    protected_paths = {
        path for path in (set(baseline) | set(current))
        if _is_managed_learning_descriptor(path) or _is_secret(path)
    }
    for path in sorted(protected_paths):
        risks.append({"path": path, "code": "protected_change_rejected"})
    for old_path in sorted(deleted):
        match = next((
            new_path for new_path in sorted(created - paired_created)
            if baseline[old_path]["sha256"] == current[new_path]["sha256"]
        ), None)
        if match:
            changed.append({
                "operation": "move", "path": old_path, "destination_path": match,
                "base_hash": baseline[old_path]["sha256"], "new_hash": current[match]["sha256"],
                "requires_separate_confirmation": True,
            })
            paired_deleted.add(old_path)
            paired_created.add(match)

    for relative in sorted((set(baseline) | set(current)) - protected_paths):
        if relative in paired_deleted or relative in paired_created:
            continue
        before = baseline.get(relative)
        after = current.get(relative)
        if before and after and before["sha256"] == after["sha256"]:
            continue
        if (before and not before["is_text"]) or (after and not after["is_text"]):
            risks.append({"path": relative, "code": "binary_change_rejected"})
            continue
        old_content = _read_text(base.joinpath(*PurePosixPath(relative).parts)) if before else ""
        new_content = _read_text(worktree.joinpath(*PurePosixPath(relative).parts)) if after else ""
        operation = "delete" if before and not after else "create" if after and not before else "write"
        entry = {
            "operation": operation, "path": relative,
            "base_hash": before["sha256"] if before else None,
            "new_hash": after["sha256"] if after else None,
            "requires_separate_confirmation": operation == "delete",
        }
        if operation != "delete":
            entry["content"] = new_content
        entry["diff"] = "".join(difflib.unified_diff(
            old_content.splitlines(keepends=True), new_content.splitlines(keepends=True),
            fromfile=f"a/{relative}", tofile=f"b/{relative}",
        ))
        changed.append(entry)
    diff = "\n".join(str(
        item.get("diff")
        or f"{item['operation']}: {item['path']}"
        + (f" -> {item['destination_path']}" if item.get("destination_path") else "")
    ) for item in changed)
    encoded = diff.encode("utf-8")
    if len(encoded) > MAX_DIFF_BYTES:
        diff = encoded[:MAX_DIFF_BYTES].decode("utf-8", errors="ignore") + "\n[diff truncated]"
        risks.append({"code": "diff_truncated", "limit": MAX_DIFF_BYTES})
    return changed, diff, risks


def _prompt_for(run: LocalAgentRun, profile: LocalAgentProfile) -> str:
    constraints = "\n".join(f"- {item}" for item in (run.constraints or [])) or "- 无附加约束"
    return f"""你是由 LearnFlow Tutor 委派的本地代码 Agent。只在当前隔离工作目录内完成任务。

任务类型：{run.task_type}
目标：{run.goal}
约束：
{constraints}

强制边界：
- 不读取或修改 .learnflow、.git、.env、密钥、凭据、符号链接或工作目录之外的路径。
- 不创建或修改 LearnFlow 讲义、练习、五核画像或数据库。
- 不提交、推送或发布；不要请求用户交互。
- 运行必要测试，并在最终结果中简要说明修改、测试与风险。
- 联网策略显示为 {profile.network_policy}；不要声称 LearnFlow 已强制断网，除非适配器明确提供该能力。
"""


async def append_run_event(db: AsyncSession, run_id: int, event_type: str, payload: dict) -> LocalAgentRunEvent:
    lock = _event_locks.setdefault(run_id, asyncio.Lock())
    async with lock:
        sequence = _event_sequences.get(run_id)
        if sequence is None:
            sequence = int((await db.execute(select(func.max(LocalAgentRunEvent.sequence)).where(
                LocalAgentRunEvent.run_id == run_id,
            ))).scalar_one_or_none() or 0)
        sequence += 1
        _event_sequences[run_id] = sequence
        event = LocalAgentRunEvent(
            run_id=run_id, sequence=sequence, event_type=event_type, payload=payload,
        )
        db.add(event)
        await db.flush()
        return event


async def ensure_seeded_profile(db: AsyncSession, learner_id: int) -> LocalAgentProfile | None:
    if not settings.competition_demo_mode:
        return None
    profile = (await db.execute(select(LocalAgentProfile).where(
        LocalAgentProfile.learner_id == learner_id,
        LocalAgentProfile.adapter == "deterministic_fake",
    ))).scalar_one_or_none()
    if profile:
        return profile
    profile = LocalAgentProfile(
        learner_id=learner_id, name="Seeded Demo Agent", adapter="deterministic_fake",
        enabled=True, priority=0, task_types=sorted(ALLOWED_TASK_TYPES),
        capabilities=["code_edit", "test"], sandbox_policy="workspace_write",
        network_policy="managed_off", timeout_seconds=60,
        last_probe={
            "available": True, "authenticated": True, "version": "seeded-demo-v1",
            "sandbox_policy": "workspace_write", "network_policy": "managed_off",
            "network_boundary_enforced": True,
        },
    )
    db.add(profile)
    await db.flush()
    return profile


async def probe_profile(profile: LocalAgentProfile) -> dict:
    return await adapter_for(profile).probe(profile)


async def select_profile(
    db: AsyncSession, learner_id: int, task_type: str, required_capabilities: list[str],
) -> LocalAgentProfile | None:
    await ensure_seeded_profile(db, learner_id)
    profiles = list((await db.execute(select(LocalAgentProfile).where(
        LocalAgentProfile.learner_id == learner_id,
        LocalAgentProfile.enabled.is_(True),
    ).order_by(LocalAgentProfile.priority.asc(), LocalAgentProfile.id.asc()))).scalars().all())
    required = set(required_capabilities)
    for profile in profiles:
        if task_type in set(profile.task_types or []) and required <= set(profile.capabilities or []):
            return profile
    return None


async def create_run_for_action(
    db: AsyncSession, action: AgentAction, profile: LocalAgentProfile, target: dict,
) -> LocalAgentRun:
    if not settings.desktop_mode:
        raise LocalAgentError(404, "本地 Agent Broker 仅在桌面版可用", "desktop_only")
    workspace = (await db.execute(select(ProjectWorkspace).where(
        ProjectWorkspace.project_id == action.project_id,
        ProjectWorkspace.learner_id == action.learner_id,
        ProjectWorkspace.status == "linked",
    ))).scalar_one_or_none()
    if not workspace:
        raise LocalAgentError(409, "请先为项目关联本地工作区", "workspace_not_linked")
    existing = (await db.execute(select(LocalAgentRun).where(
        LocalAgentRun.action_id == action.id,
    ))).scalar_one_or_none()
    if existing:
        return existing
    run = LocalAgentRun(
        learner_id=action.learner_id, project_id=action.project_id,
        checkpoint_id=action.checkpoint_id, session_id=action.session_id,
        action_id=action.id, profile_id=profile.id,
        task_type=target["task_type"], goal=target["goal"],
        constraints=list(target.get("constraints") or []),
        required_capabilities=list(target.get("required_capabilities") or []),
        status="queued", idempotency_key=f"local-agent:action:{action.id}",
        result={
            "profile": {"id": profile.id, "name": profile.name, "adapter": profile.adapter},
            "sandbox_policy": profile.sandbox_policy,
            "network_policy": profile.network_policy,
            "network_boundary_enforced": profile.adapter == "deterministic_fake",
        },
    )
    db.add(run)
    await db.flush()
    await append_run_event(db, run.id, "queued", {"profile": profile.name})
    await record_event(
        db, learner_id=action.learner_id, event_type="local_agent_started",
        source="local_agent_broker", project_id=action.project_id,
        checkpoint_id=action.checkpoint_id, session_id=action.session_id,
        payload={"run_id": run.id, "profile_id": profile.id, "task_type": run.task_type},
        provenance={"action_id": action.id}, client_event_id=f"local-agent:{run.id}:started",
    )
    await db.commit()
    schedule_run(run.id)
    return run


def schedule_run(run_id: int) -> None:
    current = _tasks.get(run_id)
    if current and not current.done():
        return
    _tasks[run_id] = asyncio.create_task(execute_run(run_id))


async def _read_stdout(
    run_id: int, process: asyncio.subprocess.Process, adapter: LocalAgentAdapter,
) -> tuple[list[dict], bool]:
    assert process.stdout is not None
    events: list[dict] = []
    consumed = 0
    truncated = False
    while True:
        raw = await process.stdout.readline()
        if not raw:
            break
        consumed += len(raw)
        if consumed > settings.local_agent_max_output_bytes:
            truncated = True
            continue
        event = adapter.parse_event(raw.decode("utf-8", errors="replace").rstrip())
        events.append(event)
        async with async_session() as db:
            await append_run_event(db, run_id, str(event.get("type") or "event"), event)
            await db.commit()
    return events, truncated


async def execute_run(run_id: int) -> None:
    process: asyncio.subprocess.Process | None = None
    adapter: LocalAgentAdapter | None = None
    stdout_task: asyncio.Task | None = None
    try:
        async with async_session() as db:
            run = await db.get(LocalAgentRun, run_id)
            if not run or run.status != "queued":
                return
            profile = await db.get(LocalAgentProfile, run.profile_id)
            workspace = (await db.execute(select(ProjectWorkspace).where(
                ProjectWorkspace.project_id == run.project_id,
                ProjectWorkspace.learner_id == run.learner_id,
                ProjectWorkspace.status == "linked",
            ))).scalar_one_or_none()
            if not profile or not profile.enabled or not workspace:
                raise LocalAgentError(409, "本地 Agent 配置或工作区已失效", "run_configuration_stale")
            root = canonical_root(workspace.root_path)
            probe = await probe_profile(profile)
            profile.last_probe = probe
            if not probe.get("available") or not probe.get("authenticated"):
                raise LocalAgentError(409, probe.get("message") or "本地 Agent 未安装或未登录", "agent_unavailable")
            isolation, worktree, manifest = await _prepare_isolation(root, run.id)
            run.isolation_root = str(isolation)
            run.base_manifest = manifest
            run.status = "running"
            run.started_at = datetime.utcnow()
            await append_run_event(db, run.id, "started", {
                "profile": profile.name, "adapter": profile.adapter,
                "sandbox_policy": profile.sandbox_policy,
                "network_policy": profile.network_policy,
                "network_boundary_enforced": bool(probe.get("network_boundary_enforced")),
            })
            await db.commit()

            adapter = adapter_for(profile)
            if profile.adapter == "deterministic_fake":
                await append_run_event(db, run.id, "analysis", {"message": "检查隔离副本"})
                target = worktree / "learnflow-seeded-agent.md"
                target.write_text(
                    "# Seeded Local Agent Result\n\n"
                    f"Task: {run.task_type}\n\nGoal: {run.goal}\n",
                    encoding="utf-8",
                )
                await append_run_event(db, run.id, "test", {"name": "seeded-check", "status": "passed"})
                events = [
                    {"type": "analysis", "message": "检查隔离副本"},
                    {"type": "test", "name": "seeded-check", "status": "passed"},
                ]
                return_code = 0
            else:
                process = await adapter.start(profile, worktree, _prompt_for(run, profile))
                assert process is not None
                _processes[run.id] = process
                stdout_task = asyncio.create_task(_read_stdout(run.id, process, adapter))
                try:
                    await asyncio.wait_for(process.wait(), timeout=profile.timeout_seconds)
                except asyncio.TimeoutError:
                    await adapter.cancel(process)
                    raise LocalAgentError(408, "本地 Agent 执行超时", "run_timeout")
                events, truncated = await stdout_task
                await db.refresh(run)
                if run.status == "canceled":
                    return
                if truncated:
                    await append_run_event(db, run.id, "output_truncated", {
                        "limit": settings.local_agent_max_output_bytes,
                    })
                return_code = process.returncode or 0

            changed, diff_text, risks = _collect_changes(base=isolation / "base", worktree=worktree)
            collected = adapter.collect_result(events, return_code)
            collected["risks"] = [*list(collected.get("risks") or []), *risks]
            collected["changed_file_count"] = len(changed)
            collected["requires_second_confirmation"] = True
            run.changed_files = changed
            run.diff_text = diff_text
            run.result = {**dict(run.result or {}), **collected}
            run.status = "completed" if return_code == 0 else "failed"
            run.finished_at = datetime.utcnow()
            await append_run_event(db, run.id, run.status, {
                "return_code": return_code, "changed_file_count": len(changed),
            })
            await record_event(
                db, learner_id=run.learner_id, event_type="local_agent_completed",
                source="local_agent_broker", project_id=run.project_id,
                checkpoint_id=run.checkpoint_id, session_id=run.session_id,
                payload={"run_id": run.id, "status": run.status, "changed_file_count": len(changed)},
                provenance={"action_id": run.action_id}, client_event_id=f"local-agent:{run.id}:completed",
            )
            await db.commit()
    except asyncio.CancelledError:
        if stdout_task and not stdout_task.done():
            stdout_task.cancel()
        if adapter:
            await adapter.cancel(process)
        raise
    except Exception as exc:
        async with async_session() as db:
            run = await db.get(LocalAgentRun, run_id)
            if run and run.status != "canceled":
                run.status = "failed"
                run.error = {
                    "code": getattr(exc, "code", "run_failed"),
                    "message": str(exc)[:500],
                }
                run.finished_at = datetime.utcnow()
                await append_run_event(db, run.id, "failed", run.error)
                await record_event(
                    db, learner_id=run.learner_id, event_type="local_agent_completed",
                    source="local_agent_broker", project_id=run.project_id,
                    checkpoint_id=run.checkpoint_id, session_id=run.session_id,
                    payload={"run_id": run.id, "status": "failed", **run.error},
                    provenance={"action_id": run.action_id}, client_event_id=f"local-agent:{run.id}:completed",
                )
                await db.commit()
    finally:
        _processes.pop(run_id, None)
        _tasks.pop(run_id, None)


async def cancel_run(db: AsyncSession, run: LocalAgentRun) -> None:
    if run.status in {"completed", "failed", "canceled", "stale", "applied"}:
        return
    run.status = "canceled"
    run.finished_at = datetime.utcnow()
    await append_run_event(db, run.id, "canceled", {})
    await record_event(
        db, learner_id=run.learner_id, event_type="local_agent_canceled",
        source="local_agent_broker", project_id=run.project_id,
        checkpoint_id=run.checkpoint_id, session_id=run.session_id,
        payload={"run_id": run.id}, provenance={"action_id": run.action_id},
        client_event_id=f"local-agent:{run.id}:canceled",
    )
    await db.commit()
    profile = await db.get(LocalAgentProfile, run.profile_id)
    if profile:
        await adapter_for(profile).cancel(_processes.get(run.id))
    task = _tasks.get(run.id)
    if task and not task.done():
        task.cancel()


async def mark_interrupted_runs_failed() -> None:
    """A process cannot be safely resumed after sidecar restart."""
    async with async_session() as db:
        runs = list((await db.execute(select(LocalAgentRun).where(
            LocalAgentRun.status.in_(["queued", "running"]),
        ))).scalars().all())
        for run in runs:
            run.status = "failed"
            run.finished_at = datetime.utcnow()
            run.error = {
                "code": "sidecar_restarted",
                "message": "桌面服务已重启；隔离任务不会自动恢复，请重新委派。",
            }
            await append_run_event(db, run.id, "failed", run.error)
        await db.commit()


def _validate_apply_target(root: Path, change: dict) -> None:
    operation = change["operation"]
    relative, target = resolve_workspace_path(
        root, change["path"], actor="agent", allow_missing_leaf=operation == "create",
    )
    if operation == "create":
        if target.exists():
            raise LocalAgentError(409, f"{relative} 已出现，结果已过期", "stale")
        return
    if not target.is_file() or sha256_file(target) != change.get("base_hash"):
        raise LocalAgentError(409, f"{relative} 已变化，结果已过期", "stale")
    if operation == "move":
        _, destination = resolve_workspace_path(
            root, change["destination_path"], actor="agent", allow_missing_leaf=True,
        )
        if destination.exists():
            raise LocalAgentError(409, f"{change['destination_path']} 已存在，结果已过期", "stale")


def _backup_apply_targets(root: Path, changes: list[dict]) -> dict[str, bytes | None]:
    backups: dict[str, bytes | None] = {}
    for change in changes:
        paths = [change["path"]]
        if change["operation"] == "move":
            paths.append(change["destination_path"])
        for relative in paths:
            _, path = resolve_workspace_path(root, relative, actor="agent", allow_missing_leaf=True)
            backups[relative] = path.read_bytes() if path.exists() and path.is_file() else None
    return backups


def _restore_apply_targets(root: Path, backups: dict[str, bytes | None]) -> None:
    for relative, content in backups.items():
        _, path = resolve_workspace_path(root, relative, actor="agent", allow_missing_leaf=True)
        if content is None:
            if path.exists() and path.is_file():
                path.unlink()
        else:
            _atomic_write(path, content)


async def apply_run_result(
    db: AsyncSession, run: LocalAgentRun, *, confirmed_deletions: list[str],
    confirmed_moves: list[str], idempotency_key: str,
) -> LocalAgentRun:
    if run.status == "applied":
        return run
    if run.status != "completed":
        raise LocalAgentError(409, "当前结果不能应用", "run_not_applicable")
    workspace = (await db.execute(select(ProjectWorkspace).where(
        ProjectWorkspace.project_id == run.project_id,
        ProjectWorkspace.learner_id == run.learner_id,
        ProjectWorkspace.status == "linked",
    ))).scalar_one_or_none()
    if not workspace:
        raise LocalAgentError(409, "项目工作区已解除关联", "workspace_unlinked")
    root = canonical_root(workspace.root_path)
    changes = list(run.changed_files or [])
    deletion_set = set(confirmed_deletions)
    move_set = set(confirmed_moves)
    missing_delete = [item["path"] for item in changes if item["operation"] == "delete" and item["path"] not in deletion_set]
    missing_move = [item["path"] for item in changes if item["operation"] == "move" and item["path"] not in move_set]
    if missing_delete or missing_move:
        raise LocalAgentError(400, "删除和移动必须逐项勾选确认", "separate_confirmation_required")
    try:
        for change in changes:
            _validate_apply_target(root, change)
    except LocalAgentError:
        run.status = "stale"
        run.error = {"code": "stale", "message": "真实工作区已变化，禁止覆盖"}
        await append_run_event(db, run.id, "stale", run.error)
        await db.commit()
        raise

    backups = _backup_apply_targets(root, changes)
    operations: list[WorkspaceOperation] = []
    try:
        for index, change in enumerate(changes):
            operation_name = change["operation"]
            payload = {
                "actor": "agent", "target_path": change["path"],
                "destination_path": change.get("destination_path"),
                "content": change.get("content"), "base_hash": change.get("base_hash"),
            }
            operation = WorkspaceOperation(
                workspace_id=workspace.id, learner_id=run.learner_id,
                project_id=run.project_id, checkpoint_id=run.checkpoint_id,
                session_id=run.session_id, actor="agent", operation=operation_name,
                status="proposed", target_path=change["path"],
                destination_path=change.get("destination_path"),
                base_hash=change.get("base_hash"), payload=payload,
                result={"local_agent_run_id": run.id},
                idempotency_key=(
                    f"local-agent-apply:{run.id}:{index}:"
                    f"{sha256_bytes(idempotency_key.encode('utf-8'))}"
                ),
            )
            db.add(operation)
            await db.flush()
            result = apply_operation(root, operation.id, operation_name, payload)
            operation.status = "applied"
            operation.confirmed_at = datetime.utcnow()
            operation.applied_at = operation.confirmed_at
            operation.result = {**result, "local_agent_run_id": run.id}
            operations.append(operation)
        run.status = "applied"
        run.applied_at = datetime.utcnow()
        run.result = {
            **dict(run.result or {}),
            "workspace_operation_ids": [item.id for item in operations],
            "applied_file_count": len(operations),
        }
        await append_run_event(db, run.id, "applied", {
            "workspace_operation_ids": [item.id for item in operations],
        })
        await record_event(
            db, learner_id=run.learner_id, event_type="local_agent_result_applied",
            source="local_agent_broker", project_id=run.project_id,
            checkpoint_id=run.checkpoint_id, session_id=run.session_id,
            payload={"run_id": run.id, "operation_ids": [item.id for item in operations]},
            provenance={"action_id": run.action_id, "second_confirmation": True},
            client_event_id=f"local-agent:{run.id}:applied",
        )
        await db.commit()
        return run
    except Exception as exc:
        failed_run_id = run.id
        await db.rollback()
        _restore_apply_targets(root, backups)
        async with async_session() as recovery_db:
            recovery_run = await recovery_db.get(LocalAgentRun, failed_run_id)
            if recovery_run:
                recovery_run.error = {
                    "code": getattr(exc, "code", "batch_apply_failed"),
                    "message": str(exc)[:500], "rollback_restored": True,
                }
                await append_run_event(recovery_db, recovery_run.id, "apply_rolled_back", recovery_run.error)
                await recovery_db.commit()
        if isinstance(exc, (LocalAgentError, WorkspaceError)):
            raise LocalAgentError(
                getattr(exc, "status_code", 409), str(exc), getattr(exc, "code", "batch_apply_failed"),
            ) from exc
        raise LocalAgentError(500, "批量应用失败，真实工作区已恢复", "batch_apply_failed") from exc
