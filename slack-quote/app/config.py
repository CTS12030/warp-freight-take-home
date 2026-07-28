"""Environment-backed settings. Secrets are read here and nowhere else."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    return int(raw) if raw else default


@dataclass(frozen=True)
class Settings:
    slack_signing_secret: str
    warp_base_url: str
    warp_api_key: str

    # A quote costs a carrier rate-shop call, so repeat lanes are served from cache.
    quote_cache_ttl_seconds: int

    # Upstream retry budget. total_deadline caps the wall clock across all attempts
    # so a user is never left waiting past the point where the answer is useful.
    max_attempts: int
    total_deadline_seconds: float

    db_path: Path

    @property
    def signing_secret_bytes(self) -> bytes:
        return self.slack_signing_secret.encode()


def load_settings() -> Settings:
    return Settings(
        slack_signing_secret=os.getenv("SLACK_SIGNING_SECRET", ""),
        warp_base_url=os.getenv("WARP_API_BASE_URL", "http://localhost:3001").rstrip("/"),
        warp_api_key=os.getenv("WARP_API_KEY", "mock"),
        quote_cache_ttl_seconds=_int("QUOTE_CACHE_TTL_SECONDS", 900),
        max_attempts=_int("WARP_MAX_ATTEMPTS", 3),
        total_deadline_seconds=float(os.getenv("WARP_TOTAL_DEADLINE_SECONDS", "45")),
        db_path=Path(os.getenv("QUOTE_LOG_DB", str(PROJECT_ROOT / "quotes.db"))),
    )


settings = load_settings()
