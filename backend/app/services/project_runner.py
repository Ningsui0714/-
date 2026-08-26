"""
Project-mode code runner (pilot: PyTorch 训练循环).

Runs a multi-file exercise project in a dedicated venv:
1. Writes exercise files into a per-exercise workspace dir
2. Lazily creates a shared venv on first run + installs requirements
3. Executes the entrypoint, captures stdout/stderr

The venv is created once and cached on disk, so subsequent runs are fast.
"""
import os
import re
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional

from app.core.config import settings

MAX_EXECUTION_TIME = 300  # seconds (training loops can take a while)
MAX_OUTPUT_SIZE = 200 * 1024  # 200KB
VENV_NAME = "learnflow-runtime"


def runtime_root() -> str:
    """Root dir for all project-mode runtime state (workspaces + venv)."""
    root = getattr(settings, "runtime_dir", "") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "runtime",
    )
    os.makedirs(root, exist_ok=True)
    return root


def venv_dir() -> str:
    return os.path.join(runtime_root(), VENV_NAME)


def workspace_dir(exercise_id: int) -> str:
    d = os.path.join(runtime_root(), "workspaces", f"ex{exercise_id}")
    os.makedirs(d, exist_ok=True)
    return d


def venv_ready() -> bool:
    """True if the runtime venv exists and has a python binary."""
    py = os.path.join(venv_dir(), "bin", "python")
    return os.path.isfile(py)


def installed_requirements() -> List[str]:
    """Requirements already installed in the runtime venv (from marker file)."""
    marker = os.path.join(venv_dir(), ".requirements")
    if not os.path.isfile(marker):
        return []
    try:
        with open(marker) as f:
            return [line.strip() for line in f if line.strip()]
    except OSError:
        return []


def _mark_installed(requirements: List[str]) -> None:
    marker = os.path.join(venv_dir(), ".requirements")
    with open(marker, "w") as f:
        f.write("\n".join(requirements))


def ensure_environment(requirements: Optional[List[str]] = None, timeout: int = 600) -> Dict:
    """
    Create the runtime venv and install requirements (idempotent, cached).

    Returns {"ready": bool, "created": bool, "installed": [...], "message": str}
    """
    requirements = requirements or []
    created = False

    if not venv_ready():
        _log("creating runtime venv ...")
        t0 = time.time()
        try:
            subprocess.run(
                [sys.executable, "-m", "venv", venv_dir()],
                check=True, capture_output=True, text=True, timeout=timeout,
            )
            created = True
        except Exception as e:
            return {"ready": False, "created": False, "installed": [],
                    "message": f"创建虚拟环境失败: {e}"}
        _log(f"venv created in {time.time()-t0:.1f}s")

    # Install missing requirements only
    have = set(installed_requirements())
    missing = [r for r in requirements if r not in have]
    if missing:
        py = os.path.join(venv_dir(), "bin", "python")
        _log(f"installing missing requirements: {missing}")
        try:
            subprocess.run(
                [py, "-m", "pip", "install", "--quiet", "--disable-pip-version-check", *missing],
                check=True, capture_output=True, text=True, timeout=timeout,
            )
            _mark_installed(requirements)
        except subprocess.CalledProcessError as e:
            return {"ready": False, "created": created, "installed": [],
                    "message": f"依赖安装失败: {e.stderr[-500:] if e.stderr else str(e)}"}

    return {"ready": True, "created": created, "installed": missing,
            "message": "环境就绪" if not missing else f"已安装: {', '.join(missing)}"}


def write_project_files(exercise_id: int, files: List[Dict]) -> str:
    """Write exercise files to the workspace dir. Returns the dir path."""
    workdir = workspace_dir(exercise_id)
    for f in files:
        name = f.get("name", "")
        if not name or ".." in name or name.startswith("/"):
            continue
        path = os.path.join(workdir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(f.get("content", ""))
    return workdir


def run_project(
    exercise_id: int,
    files: List[Dict],
    entrypoint: str,
    requirements: Optional[List[str]] = None,
    timeout: int = MAX_EXECUTION_TIME,
) -> Dict:
    """
    Ensure env, write files, run entrypoint.

    Returns:
        {"stdout": str, "stderr": str, "exit_code": int, "timed_out": bool,
         "elapsed": float, "env": {...}}
    """
    env_result = ensure_environment(requirements or [])
    if not env_result["ready"]:
        return {"stdout": "", "stderr": env_result["message"], "exit_code": -1,
                "timed_out": False, "elapsed": 0, "env": env_result}

    workdir = write_project_files(exercise_id, files)
    py = os.path.join(venv_dir(), "bin", "python")
    target = os.path.join(workdir, entrypoint or "main.py")
    if not os.path.isfile(target):
        return {"stdout": "", "stderr": f"入口文件 {entrypoint} 不存在",
                "exit_code": -1, "timed_out": False, "elapsed": 0, "env": env_result}

    t0 = time.time()
    try:
        proc = subprocess.run(
            [py, target],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        timed_out = False
    except subprocess.TimeoutExpired:
        proc = None
        timed_out = True

    elapsed = time.time() - t0

    stdout = (proc.stdout if proc else "") or ""
    stderr = (proc.stderr if proc else "") or ""
    if timed_out:
        stderr += f"\n⏱ 执行超时（>{timeout}s）。训练循环可能卡死或步数过多。"

    if len(stdout) > MAX_OUTPUT_SIZE:
        stdout = stdout[:MAX_OUTPUT_SIZE] + "\n... (输出截断)"
    if len(stderr) > MAX_OUTPUT_SIZE:
        stderr = stderr[:MAX_OUTPUT_SIZE] + "\n... (输出截断)"

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": proc.returncode if proc else -1,
        "timed_out": timed_out,
        "elapsed": round(elapsed, 2),
        "env": env_result,
    }


# ── stdout-based judging (project mode) ──

def check_stdout(stdout: str, config: Dict) -> Dict:
    """
    Judge stdout against config:
        {"pattern": "accuracy: (\\d+\\.\\d+)%", "min_accuracy": 90.0}
    Returns {"passed": bool, "expected": str, "actual": str, "detail": str}
    """
    pattern = config.get("pattern", "")
    if not pattern:
        return {"passed": False, "expected": "stdout 检查", "actual": "未配置检查规则",
                "detail": "缺少 judge_config.pattern"}

    match = re.search(pattern, stdout)
    if not match:
        return {"passed": False, "expected": f"匹配 {pattern}", "actual": "未匹配到",
                "detail": "stdout 中没有匹配到预期的输出。请检查你的 print 格式。"}

    actual = float(match.group(1))
    min_acc = float(config.get("min_accuracy", 0))
    passed = actual >= min_acc
    return {
        "passed": passed,
        "expected": f">= {min_acc}",
        "actual": f"{actual}",
        "detail": "准确率达到要求 🎉" if passed else f"准确率 {actual} 未达到 {min_acc}，继续调参试试",
    }


def _log(msg: str) -> None:
    print(f"[project_runner] {msg}", flush=True)
