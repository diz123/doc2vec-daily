"""Sync article chunks into a Gemini File Search store.

Each chunk is uploaded as its own document with custom metadata
(article_id, article_url, content_hash, chunk_index). The store itself is the
source of truth for delta detection, so the job needs no local state:
- added:   article_id not in the store
- updated: stored hash or chunk count differs -> delete old docs, upload new
- skipped: identical hash and chunk count
- deleted: article no longer published (only on full, unlimited runs)
"""
from __future__ import annotations

import hashlib
import io
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from google import genai
from google.genai import types

log = logging.getLogger(__name__)

# Our chunks are sized below this, so each uploaded document embeds as a single chunk
# (~1% of chunks, mostly large tables or code blocks, exceed it and are split server-side).
SERVER_MAX_TOKENS_PER_CHUNK = 512  # API maximum
POLL_SECONDS = 2.0
OPERATION_TIMEOUT_SECONDS = 300.0


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ArticleDoc:
    article_id: int
    url: str
    slug: str
    content_hash: str
    chunks: list[str]


@dataclass(frozen=True)
class StoredDoc:
    name: str
    content_hash: str


@dataclass
class SyncStats:
    added: int = 0
    updated: int = 0
    skipped: int = 0
    deleted: int = 0
    failed: int = 0
    files_uploaded: int = 0
    chunks_uploaded: int = 0
    failures: list[str] = field(default_factory=list)


class StoreSync:
    def __init__(self, client: genai.Client, store_display_name: str, workers: int = 4) -> None:
        self._client = client
        self._display_name = store_display_name
        self._workers = max(1, workers)
        self.store_name = ""

    def ensure_store(self) -> str:
        """Find the store by display name, creating it on first run."""
        for store in self._client.file_search_stores.list():
            if store.display_name == self._display_name and store.name:
                self.store_name = store.name
                log.info("Using File Search store %s", self.store_name)
                return self.store_name
        store = self._client.file_search_stores.create(config={"display_name": self._display_name})
        if not store.name:
            raise RuntimeError("File Search store was created without a name")
        self.store_name = store.name
        log.info("Created File Search store %s", self.store_name)
        return self.store_name

    def _existing(self) -> dict[int, list[StoredDoc]]:
        by_article: dict[int, list[StoredDoc]] = {}
        for doc in self._client.file_search_stores.documents.list(parent=self.store_name):
            meta = {m.key: m.string_value for m in (doc.custom_metadata or []) if m.key}
            raw_id = meta.get("article_id")
            if not doc.name or not raw_id or not raw_id.isdigit():
                continue
            by_article.setdefault(int(raw_id), []).append(
                StoredDoc(name=doc.name, content_hash=meta.get("content_hash") or "")
            )
        return by_article

    def _delete(self, docs: list[StoredDoc]) -> None:
        for doc in docs:
            self._client.file_search_stores.documents.delete(name=doc.name, config={"force": True})

    def _upload_chunk(self, article: ArticleDoc, index: int, text: str) -> None:
        config = types.UploadToFileSearchStoreConfig(
            display_name=f"{article.slug}#{index}",
            mime_type="text/markdown",
            custom_metadata=[
                types.CustomMetadata(key="article_id", string_value=str(article.article_id)),
                types.CustomMetadata(key="article_url", string_value=article.url),
                types.CustomMetadata(key="content_hash", string_value=article.content_hash),
                types.CustomMetadata(key="chunk_index", numeric_value=index),
            ],
            chunking_config=types.ChunkingConfig(
                white_space_config=types.WhiteSpaceConfig(
                    max_tokens_per_chunk=SERVER_MAX_TOKENS_PER_CHUNK,
                    max_overlap_tokens=0,
                )
            ),
        )
        operation = self._client.file_search_stores.upload_to_file_search_store(
            file_search_store_name=self.store_name,
            file=io.BytesIO(text.encode("utf-8")),
            config=config,
        )
        deadline = time.monotonic() + OPERATION_TIMEOUT_SECONDS
        while not operation.done:
            if time.monotonic() > deadline:
                raise TimeoutError(f"Indexing timed out for {article.slug}#{index}")
            time.sleep(POLL_SECONDS)
            operation = self._client.operations.get(operation)
        if operation.error:
            raise RuntimeError(f"Indexing failed for {article.slug}#{index}: {operation.error}")

    def sync(self, articles: list[ArticleDoc], allow_deletes: bool) -> SyncStats:
        if not self.store_name:
            self.ensure_store()
        stats = SyncStats()
        existing = self._existing()
        log.info("Store has %d documents for %d articles", sum(map(len, existing.values())), len(existing))

        pending: list[tuple[ArticleDoc, list[StoredDoc]]] = []
        for article in articles:
            old = existing.get(article.article_id, [])
            unchanged = len(old) == len(article.chunks) and all(
                d.content_hash == article.content_hash for d in old
            )
            if old and unchanged:
                stats.skipped += 1
            else:
                pending.append((article, old))
        log.info("%d articles to upload (%d chunks)", len(pending), sum(len(a.chunks) for a, _ in pending))

        # Remove stale documents first, so a partial failure leaves a chunk-count
        # mismatch that the next run detects and repairs.
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            list(pool.map(lambda item: self._delete(item[1]), [p for p in pending if p[1]]))

        # Upload every chunk of every pending article in parallel.
        failed: dict[int, str] = {}
        with ThreadPoolExecutor(max_workers=self._workers) as pool:
            futures = {
                pool.submit(self._upload_chunk, article, index, text): article
                for article, _ in pending
                for index, text in enumerate(article.chunks)
            }
            for future in as_completed(futures):
                article = futures[future]
                try:
                    future.result()
                    stats.chunks_uploaded += 1
                except Exception as exc:  # keep going; the next run retries this article
                    if article.article_id not in failed:
                        log.error("Failed to upload %s: %s", article.slug, exc)
                    failed[article.article_id] = f"{article.slug}: {exc}"

        for article, old in pending:
            if article.article_id in failed:
                stats.failed += 1
                stats.failures.append(failed[article.article_id])
            else:
                stats.files_uploaded += 1
                if old:
                    stats.updated += 1
                else:
                    stats.added += 1

        if allow_deletes:
            live_ids = {a.article_id for a in articles}
            for article_id, docs in existing.items():
                if article_id not in live_ids:
                    self._delete(docs)
                    stats.deleted += 1
        return stats
