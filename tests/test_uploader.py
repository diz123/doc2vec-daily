"""Delta logic of StoreSync against an in-memory fake of the File Search API."""
from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from tools.uploader import ArticleDoc, StoreSync


@dataclass
class FakeDocs:
    docs: dict[str, dict[str, str]] = field(default_factory=dict)  # name -> metadata
    deleted: list[str] = field(default_factory=list)

    def list(self, parent, config=None):
        return [
            SimpleNamespace(
                name=name,
                custom_metadata=[SimpleNamespace(key=k, string_value=v) for k, v in meta.items()],
            )
            for name, meta in self.docs.items()
        ]

    def delete(self, name, config=None):
        self.deleted.append(name)
        self.docs.pop(name)


class FakeStores:
    def __init__(self, docs: FakeDocs) -> None:
        self.documents = docs
        self.uploads: list[str] = []
        self._next = 0

    def list(self):
        return [SimpleNamespace(name="fileSearchStores/kb-1", display_name="kb")]

    def upload_to_file_search_store(self, file_search_store_name, file, config):
        meta = {m.key: m.string_value for m in config.custom_metadata if m.string_value is not None}
        self._next += 1
        self.documents.docs[f"doc-{self._next}"] = meta
        self.uploads.append(config.display_name)
        return SimpleNamespace(done=True, error=None)


def make_sync(existing: dict[str, dict[str, str]] | None = None, batch: int = 0):
    docs = FakeDocs(dict(existing or {}))
    stores = FakeStores(docs)
    client = SimpleNamespace(file_search_stores=stores, operations=SimpleNamespace(get=lambda op: op))
    return StoreSync(client, "kb", workers=2, upload_batch=batch), stores, docs


def article(article_id: int, content_hash: str, n_chunks: int = 2) -> ArticleDoc:
    return ArticleDoc(
        article_id=article_id,
        url=f"https://x/{article_id}",
        slug=f"{article_id}-a",
        content_hash=content_hash,
        chunks=[f"chunk {i}" for i in range(n_chunks)],
    )


def stored(article_id: int, content_hash: str) -> dict[str, str]:
    return {"article_id": str(article_id), "content_hash": content_hash}


def test_first_run_adds_everything():
    sync, stores, _ = make_sync()
    stats = sync.sync([article(1, "h1"), article(2, "h2", 3)], allow_deletes=True)
    assert (stats.added, stats.updated, stats.skipped) == (2, 0, 0)
    assert stats.chunks_uploaded == 5 and len(stores.uploads) == 5


def test_unchanged_articles_are_skipped():
    sync, stores, _ = make_sync({"d1": stored(1, "h1"), "d2": stored(1, "h1")})
    stats = sync.sync([article(1, "h1")], allow_deletes=True)
    assert (stats.added, stats.updated, stats.skipped) == (0, 0, 1)
    assert stores.uploads == []


def test_changed_article_replaces_old_documents():
    sync, stores, docs = make_sync({"d1": stored(1, "old"), "d2": stored(1, "old")})
    stats = sync.sync([article(1, "new")], allow_deletes=True)
    assert stats.updated == 1
    assert sorted(docs.deleted) == ["d1", "d2"]
    assert all(m["content_hash"] == "new" for m in docs.docs.values())


def test_partial_upload_is_repaired():
    sync, _, docs = make_sync({"d1": stored(1, "h1")})  # 1 of 2 chunks present
    stats = sync.sync([article(1, "h1", 2)], allow_deletes=True)
    assert stats.updated == 1 and len(docs.docs) == 2


def test_unpublished_article_deleted_only_on_full_runs():
    sync, _, docs = make_sync({"d9": stored(9, "h9")})
    assert sync.sync([article(1, "h1")], allow_deletes=False).deleted == 0
    assert "d9" in docs.docs
    assert sync.sync([article(1, "h1")], allow_deletes=True).deleted == 1
    assert "d9" not in docs.docs


def test_upload_batch_defers_the_rest():
    sync, _, _ = make_sync(batch=2)
    stats = sync.sync([article(i, f"h{i}") for i in range(5)], allow_deletes=True)
    assert stats.added == 2 and stats.deferred == 3
    assert len(stats.in_store_ids) == 2
