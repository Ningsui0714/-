from __future__ import annotations

import uuid

from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


def _registration(username: str) -> dict:
    return {
        "username": username,
        "password": "learnflow-pass-123",
        "display_name": username,
        "education_stage": "undergraduate",
        "background": "Python 基础",
        "focus_areas": ["工程实践"],
        "weekly_hours": 5,
        "preferred_modes": ["explanation", "practice"],
        "career_goal": "",
        "career_goal_status": "exploring",
    }


def test_uploaded_reference_file_stays_outside_project_workspace(tmp_path, monkeypatch):
    upload_root = tmp_path / "source-uploads"
    cache_root = tmp_path / "source-cache"
    workspace_root = tmp_path / "project-workspace"
    workspace_root.mkdir()
    monkeypatch.setattr(settings, "source_uploads_dir", str(upload_root))
    monkeypatch.setattr(settings, "source_cache_dir", str(cache_root))

    with TestClient(app) as client:
        username = f"upload_boundary_{uuid.uuid4().hex[:10]}"
        registered = client.post("/api/auth/register", json=_registration(username))
        assert registered.status_code == 200, registered.text
        project = client.post(
            "/api/projects",
            json={"name": "参考来源边界", "description": "", "user_level": "beginner"},
        ).json()

        uploaded = client.post(
            f"/api/projects/{project['id']}/sources/upload",
            files={"file": ("notes?.md", b"# Reference\n\nThis is uploaded reference content for chunking.\n", "text/markdown")},
        )
        assert uploaded.status_code == 200, uploaded.text
        source = uploaded.json()
        assert source["type"] == "file"
        assert source["url"] == "notes?.md"

        processed = client.post(
            f"/api/projects/{project['id']}/sources/{source['id']}/process"
        )
        assert processed.status_code == 200, processed.text
        assert processed.json()["chunk_count"] > 0

        assert (upload_root / str(registered.json()["learner_id"]) / str(project["id"]) / str(source["id"]) / "notes?.md").is_file()
        assert (cache_root / str(source["id"])).is_dir()
        assert not (workspace_root / "notes?.md").exists()
