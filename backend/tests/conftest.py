import os
import tempfile
from pathlib import Path


_test_dir = Path(tempfile.mkdtemp(prefix="learnflow-tutor-tests-"))
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_test_dir / 'test.db'}"
os.environ["LLM_API_KEY"] = ""
