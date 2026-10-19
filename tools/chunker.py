"""Split an article's Markdown body into heading-aligned, self-describing chunks.

Gemini File Search caps a chunk at 512 tokens, so each chunk is sized to fit in
one server-side chunk (measured ~2.9-3.5 chars/token for this content):
- split on H2 (`## `) sections, never inside a fenced code block
- a section longer than the limit is split on paragraph boundaries (then lines),
  repeating its heading as "(continued)" so the piece keeps its context
- consecutive small sections are packed together up to the limit
- image links become "(Image: alt text)": the URL costs tokens but adds no meaning
- every chunk starts with the article title and its "Article URL:" line, so the
  assistant can cite the source no matter which chunk is retrieved
"""
from __future__ import annotations

import re
from collections.abc import Callable

MAX_CHUNK_CHARS = 1400  # including the title/URL header; ~400-480 tokens
_FENCE = "```"
_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]*\)")


def _is_fence(line: str) -> bool:
    return line.lstrip().startswith(_FENCE)


def _split_sections(lines: list[str], is_boundary: Callable[[str], bool]) -> list[str]:
    blocks: list[list[str]] = [[]]
    in_fence = False
    for line in lines:
        if _is_fence(line):
            in_fence = not in_fence
        elif not in_fence and is_boundary(line) and blocks[-1]:
            blocks.append([])
        blocks[-1].append(line)
    return ["\n".join(b).strip() for b in blocks if any(line.strip() for line in b)]


def _paragraphs(lines: list[str]) -> list[str]:
    paras: list[list[str]] = [[]]
    in_fence = False
    for line in lines:
        if _is_fence(line):
            in_fence = not in_fence
        if not in_fence and not line.strip():
            if paras[-1]:
                paras.append([])
            continue
        paras[-1].append(line)
    return ["\n".join(p) for p in paras if p]


def _pack(units: list[str], limit: int, continuation: str = "") -> list[str]:
    """Greedily join units with blank lines while staying under `limit` characters."""
    packed: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n\n{unit}" if current else unit
        if current and len(candidate) > limit:
            packed.append(current)
            current = f"{continuation}\n\n{unit}" if continuation else unit
        else:
            current = candidate
    if current:
        packed.append(current)
    return packed


def _split_long_section(section: str, limit: int) -> list[str]:
    if len(section) <= limit:
        return [section]
    lines = section.split("\n")
    heading = lines[0] if lines[0].startswith("## ") else ""
    units: list[str] = []
    for para in _paragraphs(lines):
        if len(para) > limit and not _is_fence(para):
            units.extend(_pack(para.split("\n"), limit))  # oversized list/table: split by lines
        else:
            units.append(para)
    return _pack(units, limit, continuation=f"{heading} (continued)" if heading else "")


def chunk_markdown(title: str, url: str, body: str, max_chars: int = MAX_CHUNK_CHARS) -> list[str]:
    """Return chunk texts for one article, each prefixed with title and source URL."""
    header = f"# {title}\n\nArticle URL: {url}"
    limit = max(200, max_chars - len(header) - 2)
    body = _IMAGE_RE.sub(lambda m: f"(Image: {m.group(1)})" if m.group(1).strip() else "", body)
    units: list[str] = []
    for section in _split_sections(body.split("\n"), lambda line: line.startswith("## ")):
        units.extend(_split_long_section(section, limit))
    return [f"{header}\n\n{text}\n" for text in _pack(units, limit)] or [f"{header}\n"]
