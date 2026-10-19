"""Inspect the File Search store: document counts, and optionally the chunks of matching articles.

Usage:
    python check_store.py            # store totals
    python check_store.py youtube    # also list documents whose name contains "youtube"
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv
from google import genai

from tools.config import Settings


def main() -> int:
    load_dotenv()
    settings = Settings.from_env()
    client = genai.Client(api_key=settings.gemini_api_key)
    store = next(
        (s for s in client.file_search_stores.list() if s.display_name == settings.store_display_name),
        None,
    )
    if store is None or not store.name:
        print(f"Store '{settings.store_display_name}' not found")
        return 1

    print(f"Store:   {store.display_name} ({store.name})")
    print(f"Active:  {store.active_documents_count or 0} documents")
    print(f"Pending: {store.pending_documents_count or 0}   Failed: {store.failed_documents_count or 0}")
    print(f"Size:    {(store.size_bytes or 0) / 1024:.0f} KB")

    if len(sys.argv) > 1:
        needle = sys.argv[1].lower()
        print(f"\nDocuments matching '{needle}':")
        for doc in client.file_search_stores.documents.list(parent=store.name, config={"page_size": 20}):
            if needle in (doc.display_name or "").lower():
                meta = {m.key: m.string_value or m.numeric_value for m in (doc.custom_metadata or [])}
                print(f"  {doc.display_name:<70} {doc.state.value if doc.state else '':<13} {meta.get('article_url', '')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
