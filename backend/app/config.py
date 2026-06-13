"""Application configuration — loads environment variables and sets up paths."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from project root (one level above backend/)
_env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(dotenv_path=_env_path)

# ── API keys ──────────────────────────────────────────────────────────────────
XAI_API_KEY: str = os.getenv("XAI_API_KEY", "")
YUTORI_API_KEY: str = os.getenv("YUTORI_API_KEY", "")

# ── Server ────────────────────────────────────────────────────────────────────
BACKEND_HOST: str = os.getenv("BACKEND_HOST", "0.0.0.0")
BACKEND_PORT: int = int(os.getenv("BACKEND_PORT", "8000"))

# ── File storage ──────────────────────────────────────────────────────────────
UPLOAD_DIR: Path = Path(os.getenv("UPLOAD_DIR", str(Path(__file__).resolve().parent.parent / "uploads")))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_PATH: Path = Path(__file__).resolve().parent.parent / "claimguard.db"

# ── Grok / xAI ───────────────────────────────────────────────────────────────
XAI_BASE_URL: str = "https://api.x.ai/v1"
XAI_MODEL: str = os.getenv("XAI_MODEL", "grok-4.3")

# ── Yutori ────────────────────────────────────────────────────────────────────
YUTORI_BASE_URL: str = "https://api.yutori.com/v1"

# ── Security ──────────────────────────────────────────────────────────────────
INTERNAL_API_KEY: str = os.getenv("INTERNAL_API_KEY", "")
ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
ALLOWED_ORIGINS: list[str] = os.getenv(
    "ALLOWED_ORIGINS", "http://localhost:3000,http://localhost:3001"
).split(",")
MAX_CONCURRENT_PIPELINES: int = int(os.getenv("MAX_CONCURRENT_PIPELINES", "10"))

# ── Ed25519 signing ──────────────────────────────────────────────────────────
ED25519_PRIVATE_KEY_B64: str = os.getenv("ED25519_PRIVATE_KEY_B64", "")
ED25519_PRIVATE_KEY_FILE: str = os.getenv("ED25519_PRIVATE_KEY_FILE", "")

# ── OpenTelemetry ────────────────────────────────────────────────────────────
OTEL_ENABLED: bool = os.getenv("OTEL_ENABLED", "false").lower() in ("true", "1", "yes")
OTEL_SERVICE_NAME: str = os.getenv("OTEL_SERVICE_NAME", "aubric-claimguard")
OTEL_EXPORTER_OTLP_ENDPOINT: str = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
