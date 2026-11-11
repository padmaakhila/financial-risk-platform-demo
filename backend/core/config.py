"""Application settings read from environment variables (and an optional .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
INSECURE_DEFAULT_KEY = "change-me-change-me-change-me-change-me"


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader. Real environment variables always win."""
    if not path.exists():
        return

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, _, value = line.partition("=")
        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


@dataclass(frozen=True)
class Settings:
    app_env: str = "development"
    database_url: str = ""
    secret_key: str = INSECURE_DEFAULT_KEY
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 30
    upload_dir: Path = BASE_DIR / "data" / "uploads"
    max_upload_mb: int = 10
    allowed_extensions: tuple = (".pdf", ".png", ".jpg", ".jpeg", ".csv")

    # "runner" keeps the existing workflow engine; "langgraph" enables LangGraph.
    workflow_engine: str = "runner"
    workflow_fallback: bool = True
    langfuse_enabled: bool = False
    langfuse_public_key: str = field(default="", repr=False)
    langfuse_secret_key: str = field(default="", repr=False)
    langfuse_host: str = "https://cloud.langfuse.com"

    llm_provider: str = "ollama"
    ollama_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5:1.5b"
    llm_timeout_seconds: int = 240
    llm_api_enabled: bool = False
    llm_api_url: str = ""
    llm_api_key: str = field(default="", repr=False)
    llm_api_model: str = ""
    tesseract_cmd: str = ""
    erp_mock_url: str = "http://localhost:8101"
    vendor_mock_url: str = "http://localhost:8102"
    backend_url: str = "http://localhost:8000"
    log_level: str = "INFO"

    @property
    def is_production(self) -> bool:
        return self.app_env.lower() == "production"


def _bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    _load_dotenv(BASE_DIR / ".env")
    e = os.environ.get

    upload = Path(e("UPLOAD_DIR", "data/uploads"))
    if not upload.is_absolute():
        upload = BASE_DIR / upload

    workflow_engine = e("WORKFLOW_ENGINE", "runner").strip().lower()
    if workflow_engine not in {"runner", "langgraph"}:
        raise RuntimeError(
            "WORKFLOW_ENGINE must be either 'runner' or 'langgraph'."
        )

    s = Settings(
        app_env=e("APP_ENV", "development"),
        database_url=e("DATABASE_URL", ""),
        secret_key=e("SECRET_KEY", INSECURE_DEFAULT_KEY),
        access_token_minutes=int(e("ACCESS_TOKEN_MINUTES", "30")),
        upload_dir=upload,
        max_upload_mb=int(e("MAX_UPLOAD_MB", "10")),
        workflow_engine=workflow_engine,
        workflow_fallback=_bool(e("WORKFLOW_FALLBACK", "true")),
        langfuse_enabled=_bool(e("LANGFUSE_ENABLED", "false")) and bool(e("LANGFUSE_PUBLIC_KEY", "")) and bool(e("LANGFUSE_SECRET_KEY", "")),
        langfuse_public_key=e("LANGFUSE_PUBLIC_KEY", ""),
        langfuse_secret_key=e("LANGFUSE_SECRET_KEY", ""),
        langfuse_host=e("LANGFUSE_HOST", "https://cloud.langfuse.com"),
        llm_provider=e("LLM_PROVIDER", "ollama").lower(),
        ollama_url=e("OLLAMA_URL", "http://localhost:11434"),
        ollama_model=e("OLLAMA_MODEL", "qwen2.5:1.5b"),
        llm_timeout_seconds=int(e("LLM_TIMEOUT_SECONDS", "120")),
        llm_api_enabled=_bool(e("LLM_API_ENABLED", "false")),
        llm_api_url=e("LLM_API_URL", ""),
        llm_api_key=e("LLM_API_KEY", ""),
        llm_api_model=e("LLM_API_MODEL", ""),
        tesseract_cmd=e("TESSERACT_CMD", ""),
        erp_mock_url=e("ERP_MOCK_URL", "http://localhost:8101"),
        vendor_mock_url=e("VENDOR_MOCK_URL", "http://localhost:8102"),
        backend_url=e("BACKEND_URL", "http://localhost:8000"),
        log_level=e("LOG_LEVEL", "INFO"),
    )

    if not s.database_url:
        raise RuntimeError("DATABASE_URL is missing from .env.")

    if s.is_production and (
        s.secret_key == INSECURE_DEFAULT_KEY or len(s.secret_key) < 32
    ):
        raise RuntimeError(
            "SECRET_KEY must be set to a random value of 32+ characters in production."
        )

    return s