"""Sanity check: ask the assistant a question, grounded on the File Search store.

Usage:
    python ask.py "How do I add a YouTube video?"
"""
from __future__ import annotations

import sys

from dotenv import load_dotenv
from google import genai
from google.genai import types

from tools.config import Settings
from tools.uploader import find_store

# Verbatim from the brief.
SYSTEM_PROMPT = """You are OptiBot, the customer-support bot for OptiSigns.com.
• Tone: helpful, factual, concise.
• Only answer using the uploaded docs.
• Max 5 bullet points; else link to the doc.
• Cite up to 3 "Article URL:" lines per reply."""

DEFAULT_QUESTION = "How do I add a YouTube video?"


def main() -> int:
    load_dotenv()
    settings = Settings.from_env()
    if not settings.gemini_api_key:
        print("GEMINI_API_KEY is not set (see .env.sample)")
        return 1
    question = " ".join(sys.argv[1:]).strip() or DEFAULT_QUESTION
    client = genai.Client(api_key=settings.gemini_api_key)
    store = find_store(client, settings.store_display_name)
    if not store:
        print(f"File Search store '{settings.store_display_name}' not found; run main.py first")
        return 1

    response = client.models.generate_content(
        model=settings.chat_model,
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            tools=[types.Tool(file_search=types.FileSearch(file_search_store_names=[store]))],
        ),
    )

    print(f"Model: {settings.chat_model}   Store: {store}")
    print(f"\nQ: {question}\n")
    print(f"A:\n{(response.text or '').strip()}\n")

    candidate = response.candidates[0] if response.candidates else None
    grounding = candidate.grounding_metadata if candidate else None
    sources = []
    for chunk in (grounding.grounding_chunks or []) if grounding else []:
        ctx = chunk.retrieved_context
        if ctx is not None and ctx.title and ctx.title not in sources:
            sources.append(ctx.title)
    if sources:
        print("Retrieved chunks:")
        for title in sources:
            print(f"  - {title}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
