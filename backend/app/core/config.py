import os

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings
from typing import List


DEFAULT_ENV_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))), ".env"
)
CONFIGURED_ENV_PATH = os.environ.get("LEARNFLOW_SETTINGS_PATH")
ENV_FILES = (
    (DEFAULT_ENV_PATH, CONFIGURED_ENV_PATH)
    if CONFIGURED_ENV_PATH and CONFIGURED_ENV_PATH != DEFAULT_ENV_PATH
    else (DEFAULT_ENV_PATH,)
)


class Settings(BaseSettings):
    app_name: str = "LearnFlow"
    app_version: str = "0.1.0"

    # LLM
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_model: str = "gpt-4o-mini"

    # Vision (image understanding) — Moonshot
    vision_api_key: str = ""
    vision_base_url: str = "https://api.moonshot.cn/v1"
    vision_model: str = "moonshot-v1-8k-vision-preview"
    vision_api_enhance: bool = False  # allow paid API captioning of pure graphics

    # Reference-source cache. This is deliberately outside any linked project
    # workspace: GitHub/URL processing may persist images and markdown here for
    # rendering, but those files are not project files.
    source_cache_dir: str = Field(
        default="data/repo-files",
        validation_alias=AliasChoices("SOURCE_CACHE_DIR", "REPO_FILES_DIR"),
    )
    # Uploaded reference originals also live outside project workspaces.
    source_uploads_dir: str = Field(
        default="data/source-uploads",
        validation_alias="SOURCE_UPLOADS_DIR",
    )
    max_source_upload_bytes: int = 25 * 1024 * 1024

    # Project-mode runtime (venv + workspaces for multi-file exercises)
    runtime_dir: str = ""  # empty → <backend>/runtime

    # Database
    database_url: str = "sqlite+aiosqlite:///./learnflow.db"
    five_kernel_enabled: bool = True
    memory_auto_synthesis_enabled: bool = False
    github_token: str = ""
    github_resource_search_enabled: bool = True
    dev_test_login_enabled: bool = True
    competition_demo_mode: bool = False
    # Optional external adapter for the岗位典型工作任务转化 service.  LearnFlow
    # never forwards a caller supplied host, so this cannot become an open
    # proxy.  The external workflow only returns validated learning artifacts
    # and never writes five-kernel learner state directly.
    learning_task_conversion_base_url: str = "https://82.156.199.145"
    learning_task_conversion_timeout_seconds: float = 30.0
    # Machine-to-machine entry used by the personalized-learning shell.  When
    # unset, the endpoint is available only from loopback in development.
    learning_task_conversion_integration_token: str = ""
    # Desktop sidecar mode. Keep disabled in browser/server deployments.
    desktop_mode: bool = False
    desktop_token: str = ""
    local_agent_runs_dir: str = ""  # empty -> platform temp directory
    local_agent_default_timeout_seconds: int = 900
    local_agent_max_output_bytes: int = 2 * 1024 * 1024
    auth_cookie_name: str = "learnflow_session"
    auth_session_days: int = 7
    auth_cookie_secure: bool = False

    # Embedding
    embedding_backend: str = "local"  # local | api
    embedding_model: str = "text-embedding-ada-002"  # for api backend
    embedding_api_key: str = ""  # separate from llm_api_key
    embedding_base_url: str = ""  # separate from llm_base_url (empty = use llm_base_url)

    # CORS — stored as comma-separated in env, split at use
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    log_level: str = "info"

    class Config:
        # Desktop settings override the repository .env when present. Falling
        # back to the repository file keeps existing local credentials usable
        # after upgrading from older desktop builds that did not persist a
        # separate settings.env yet.
        env_file = ENV_FILES

    @property
    def cors_origins_list(self) -> List[str]:
        return [s.strip() for s in self.cors_origins.split(",") if s.strip()]

    @property
    def repo_files_dir(self) -> str:
        """Compatibility alias for integrations using the old setting name."""
        return self.source_cache_dir


settings = Settings()
