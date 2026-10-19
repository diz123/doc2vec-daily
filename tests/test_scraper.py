from types import SimpleNamespace

from tools.scraper import Article, iter_articles


class FakeSession:
    def __init__(self, pages):
        self.pages = pages
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        payload = self.pages[len(self.urls) - 1]
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: payload)


def raw(i, draft=False):
    return {"id": i, "title": f"T{i}", "html_url": f"https://x/hc/articles/{i}-T{i}", "body": "<p>b</p>",
            "updated_at": "2026-01-01T00:00:00Z", "draft": draft}


def test_follows_pagination_and_skips_drafts():
    session = FakeSession([
        {"articles": [raw(1), raw(2, draft=True)], "next_page": "https://x/page2"},
        {"articles": [raw(3)], "next_page": None},
    ])
    ids = [a.id for a in iter_articles("https://x", "en-us", session=session)]
    assert ids == [1, 3]
    assert session.urls[1] == "https://x/page2"


def test_limit_stops_early():
    session = FakeSession([{"articles": [raw(1), raw(2), raw(3)], "next_page": "https://x/p2"}])
    assert len(list(iter_articles("https://x", "en-us", limit=2, session=session))) == 2
    assert len(session.urls) == 1


def test_slug_is_filesystem_safe():
    a = Article(id=7, title="t", html_url="https://x/hc/en-us/articles/7-Hello-World%E2%80%99s", body="", updated_at="")
    assert a.slug == "7-hello-world-e2-80-99s"
