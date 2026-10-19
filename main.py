"""Sync job entry point: scrape -> Markdown -> chunk -> Gemini File Search (delta only).

Usage:
    python main.py               # full run
    python main.py --skip-upload # scrape and write Markdown only
Exit code is 0 on success, 1 if any article failed to sync.
"""
from __future__ import annotations

import argparse
import logging
import sys

from dotenv import load_dotenv
from google import genai

from tools.chunker import chunk_markdown
from tools.config import Settings
from tools.converter import html_to_markdown, render_document
from tools.runlog import LOG_FORMAT, RunLog
from tools.scraper import iter_articles
from tools.uploader import ArticleDoc, StoreSync, content_hash

log = logging.getLogger("doc2vec")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--skip-upload", action="store_true", help="scrape and write Markdown only")
    args = parser.parse_args()

    load_dotenv()
    logging.basicConfig(level=logging.INFO, format=LOG_FORMAT)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    run_log = RunLog()
    run_log.attach(logging.getLogger())
    settings = Settings.from_env()
    summary: dict[str, object] = {"status": "failed"}
    try:
        exit_code = _run(settings, args.skip_upload, summary)
    except Exception:
        log.exception("Run failed")
        exit_code = 1
    if settings.log_dir:
        try:
            log.info("Writing run log to %s", settings.log_dir)
            run_log.write(settings.log_dir, summary)
        except OSError as exc:
            log.error("Could not write run log to %s: %s", settings.log_dir, exc)
    return exit_code


def _run(settings: Settings, skip_upload: bool, summary: dict[str, object]) -> int:
    full_run = settings.max_articles == 0
    if not skip_upload and not settings.gemini_api_key:
        log.error("GEMINI_API_KEY is not set (see .env.sample)")
        return 1

    # 1) Scrape + convert, writing one Markdown file per article.
    settings.output_dir.mkdir(parents=True, exist_ok=True)
    docs: list[ArticleDoc] = []
    written: set[str] = set()
    for article in iter_articles(settings.zendesk_base_url, settings.zendesk_locale, limit=settings.max_articles):
        body = html_to_markdown(article.body, settings.zendesk_base_url)
        document = render_document(article, body)
        filename = f"{article.slug}.md"
        (settings.output_dir / filename).write_text(document, encoding="utf-8", newline="\n")
        written.add(filename)
        docs.append(
            ArticleDoc(
                article_id=article.id,
                url=article.html_url,
                slug=article.slug,
                content_hash=content_hash(document),
                chunks=chunk_markdown(article.title, article.html_url, body),
            )
        )
    if full_run:  # drop files of unpublished/renamed articles
        for stale in settings.output_dir.glob("*.md"):
            if stale.name not in written:
                stale.unlink()
    log.info("Wrote %d Markdown files to %s (%d chunks)", len(docs), settings.output_dir, sum(len(d.chunks) for d in docs))
    summary.update(articles_scraped=len(docs), chunks_total=sum(len(d.chunks) for d in docs))
    if skip_upload:
        summary["status"] = "ok (upload skipped)"
        return 0

    # 2) Delta upload to the File Search store.
    sync = StoreSync(
        genai.Client(api_key=settings.gemini_api_key),
        settings.store_display_name,
        workers=settings.upload_workers,
        upload_batch=settings.upload_batch,
    )
    stats = sync.sync(docs, allow_deletes=full_run)
    log.info(
        "Sync done: added=%d updated=%d skipped=%d deleted=%d failed=%d deferred=%d | embedded files=%d chunks=%d",
        stats.added, stats.updated, stats.skipped, stats.deleted, stats.failed, stats.deferred,
        stats.files_uploaded, stats.chunks_uploaded,
    )
    synced = [d for d in docs if d.article_id in stats.in_store_ids]
    log.info(
        "Store total: files=%d chunks=%d (%s)",
        len(synced), sum(len(d.chunks) for d in synced), sync.store_name,
    )
    summary.update(
        status="failed" if stats.failed else "ok",
        added=stats.added, updated=stats.updated, skipped=stats.skipped,
        deleted=stats.deleted, failed=stats.failed, deferred=stats.deferred,
        embedded_files=stats.files_uploaded, embedded_chunks=stats.chunks_uploaded,
        store_files=len(synced), store_chunks=sum(len(d.chunks) for d in synced),
        failures=stats.failures,
    )
    return 1 if stats.failed else 0


if __name__ == "__main__":
    sys.exit(main())
