"""Runtime configuration loaded from environment variables."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    zendesk_base_url: str
    zendesk_locale: str
    max_articles: int  # 0 means no limit
    output_dir: Path
    gemini_api_key: str
    store_display_name: str
    upload_workers: int

    @classmethod
    def from_env(cls) -> "Settings":
        base_url = os.getenv("ZENDESK_BASE_URL", "").strip().rstrip("/")
        if not base_url:
            raise ValueError("ZENDESK_BASE_URL is required (see .env.sample)")
        return cls(
            zendesk_base_url=base_url,
            zendesk_locale=os.getenv("ZENDESK_LOCALE", "").strip() or "en-us",
            max_articles=_int_env("MAX_ARTICLES", 0),
            output_dir=Path(os.getenv("OUTPUT_DIR", "").strip() or "data/articles"),
            gemini_api_key=os.getenv("GEMINI_API_KEY", "").strip(),
            store_display_name=os.getenv("FILE_SEARCH_STORE", "").strip() or "help-center-kb",
            upload_workers=_int_env("UPLOAD_WORKERS", 4),
        )
