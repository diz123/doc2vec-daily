"""Zendesk Help Center client: lists published articles via the public API.

Using the API instead of crawling HTML pages means `body` already contains
only the article content (no site nav, header, footer or ads).
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

log = logging.getLogger(__name__)

PAGE_SIZE = 100  # Zendesk maximum
TIMEOUT_SECONDS = 30
_SLUG_UNSAFE_RE = re.compile(r"[^a-z0-9-]+")


@dataclass(frozen=True)
class Article:
    id: int
    title: str
    html_url: str
    body: str
    updated_at: str

    @property
    def slug(self) -> str:
        """Stable filename stem derived from the canonical URL, e.g. '123-how-to-x'."""
        tail = self.html_url.rstrip("/").rsplit("/", 1)[-1].lower()
        slug = _SLUG_UNSAFE_RE.sub("-", tail).strip("-")[:120]
        return slug or str(self.id)


def build_session() -> requests.Session:
    """HTTP session that retries rate limits (honouring Retry-After) and 5xx errors."""
    retry = Retry(
        total=5,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers.update({"User-Agent": "kb-sync/1.0", "Accept": "application/json"})
    return session


def _to_article(raw: dict[str, Any]) -> Article:
    return Article(
        id=int(raw["id"]),
        title=str(raw.get("title") or "").strip(),
        html_url=str(raw["html_url"]),
        body=str(raw.get("body") or ""),
        updated_at=str(raw.get("updated_at") or ""),
    )


def iter_articles(
    base_url: str,
    locale: str,
    limit: int = 0,
    session: requests.Session | None = None,
) -> Iterator[Article]:
    """Yield published articles, following `next_page` until exhausted or `limit` is hit."""
    session = session or build_session()
    url: str | None = f"{base_url}/api/v2/help_center/{locale}/articles.json?per_page={PAGE_SIZE}"
    yielded = 0
    page = 0
    while url:
        page += 1
        resp = session.get(url, timeout=TIMEOUT_SECONDS)
        resp.raise_for_status()
        payload = resp.json()
        articles = payload.get("articles", [])
        log.info("Fetched page %d (%d articles)", page, len(articles))
        for raw in articles:
            if raw.get("draft"):
                continue
            yield _to_article(raw)
            yielded += 1
            if limit and yielded >= limit:
                return
        url = payload.get("next_page")
