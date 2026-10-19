from tools.chunker import MAX_CHUNK_CHARS, chunk_markdown

TITLE = "How to Use X"
URL = "https://help.example.com/hc/en-us/articles/1-How-to-Use-X"


def sections(n: int, size: int) -> str:
    return "\n\n".join(f"## Section {i}\n\n" + ("word " * (size // 5)).strip() for i in range(n))


def test_every_chunk_carries_title_and_source_url():
    chunks = chunk_markdown(TITLE, URL, sections(8, 600))
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.startswith(f"# {TITLE}\n\nArticle URL: {URL}\n\n")


def test_chunks_respect_size_limit():
    for chunk in chunk_markdown(TITLE, URL, sections(20, 900)):
        assert len(chunk) <= MAX_CHUNK_CHARS + 1  # trailing newline


def test_small_sections_are_packed_together():
    chunks = chunk_markdown(TITLE, URL, sections(4, 50))
    assert len(chunks) == 1
    assert "## Section 0" in chunks[0] and "## Section 3" in chunks[0]


def test_long_section_is_split_with_continued_heading():
    body = "## Big\n\n" + "\n\n".join(("para %d " % i) * 40 for i in range(12))
    chunks = chunk_markdown(TITLE, URL, body)
    assert len(chunks) > 1
    assert all("## Big" in c for c in chunks)
    assert any("## Big (continued)" in c for c in chunks[1:])


def test_never_splits_inside_code_fence():
    code = "```\n" + "\n".join(f"line {i}" for i in range(30)) + "\n## not a heading\n```"
    body = "## Script\n\n" + code + "\n\n## After\n\ntext"
    for chunk in chunk_markdown(TITLE, URL, body):
        assert chunk.count("```") % 2 == 0


def test_image_links_become_alt_text():
    chunks = chunk_markdown(TITLE, URL, "## A\n\n![Apps button](https://x/img.png) Click it.")
    assert "(Image: Apps button)" in chunks[0]
    assert "img.png" not in chunks[0]


def test_empty_body_still_yields_header_chunk():
    assert chunk_markdown(TITLE, URL, "") == [f"# {TITLE}\n\nArticle URL: {URL}\n"]
