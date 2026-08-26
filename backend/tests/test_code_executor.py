import subprocess
import sys
from pathlib import Path

from app.services import code_executor, project_runner


def test_frozen_executor_uses_sidecar_script_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(project_runner, "venv_dir", lambda: str(tmp_path / "missing-runtime"))
    monkeypatch.setattr(code_executor.sys, "frozen", True, raising=False)
    monkeypatch.setattr(code_executor.sys, "executable", "/Applications/LearnFlow.app/backend")

    assert code_executor._python_command("/tmp/exercise.py") == [
        "/Applications/LearnFlow.app/backend",
        "--run-python-script",
        "/tmp/exercise.py",
    ]


def test_desktop_sidecar_script_mode_executes_python(tmp_path):
    script = tmp_path / "answer.py"
    script.write_text("value = input().strip()\nprint(value.upper())\n", encoding="utf-8")
    entrypoint = Path(__file__).parents[1] / "desktop_entry.py"

    result = subprocess.run(
        [sys.executable, str(entrypoint), "--run-python-script", str(script)],
        input="learnflow\n",
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "LEARNFLOW\n"


def test_source_executor_still_runs_scripts():
    result = code_executor.execute_code(
        "value = int(input())\nprint(value * 2)",
        test_input="21\n",
    )

    assert result["exit_code"] == 0
    assert result["stdout"].strip() == "42"
