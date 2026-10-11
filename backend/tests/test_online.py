import httpx
import pytest

from app.integrations import online


class Resp:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("x", request=None, response=None)

    def json(self):
        return self.payload


GUT = {"results": [
    {"id": 1, "title": "Something Else Entirely", "authors": [{"name": "Nobody, Some"}], "formats": {}},
    {"id": 2680, "title": "Meditations", "authors": [{"name": "Marcus Aurelius, Emperor of Rome"}],
     "formats": {"application/epub+zip": "http://e.epub", "text/html": "http://g/2680.html.images"}}]}


def fake(gut=None, ol=None, calls=None):
    def get(url, params=None, **kw):
        if calls is not None:
            calls.append(url)
        if isinstance(gut, Exception) and "gutendex" in url:
            raise gut
        return Resp(gut if "gutendex" in url else ol)
    return get


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(online, "CACHE_DIR", tmp_path)
    online._mem.clear()


def test_gutenberg_match(monkeypatch):
    monkeypatch.setattr(online.httpx, "get", fake(GUT, {"docs": []}))
    r = online.lookup("Meditations", "Marcus Aurelius")
    assert r["gutenberg"] == {"url": "https://www.gutenberg.org/ebooks/2680",
                              "read_url": "http://g/2680.html.images", "formats": ["html", "epub"]}
    assert r["openlibrary"] is None


def test_gutenberg_wrong_author_rejected(monkeypatch):
    monkeypatch.setattr(online.httpx, "get", fake(GUT, {"docs": []}))
    assert online.lookup("Meditations", "Daniel Kahneman")["gutenberg"] is None


def test_openlibrary_public(monkeypatch):
    ol = {"docs": [{"key": "/works/OL1W", "title": "Meditations", "author_name": ["Marcus Aurelius"],
                    "ebook_access": "public", "ia": ["meditations00marc"]}]}
    monkeypatch.setattr(online.httpx, "get", fake({"results": []}, ol))
    r = online.lookup("Meditations", "Marcus Aurelius")
    assert r["gutenberg"] is None
    assert r["openlibrary"] == {"access": "public", "url": "https://openlibrary.org/works/OL1W",
                                "read_url": "https://archive.org/details/meditations00marc"}


def test_openlibrary_borrowable_and_ignores_printdisabled(monkeypatch):
    ol = {"docs": [
        {"key": "/works/A", "title": "Thinking, Fast and Slow", "author_name": ["Daniel Kahneman"],
         "ebook_access": "printdisabled"},
        {"key": "/works/B", "title": "Thinking, Fast and Slow", "author_name": ["Daniel Kahneman"],
         "ebook_access": "borrowable", "ia": ["x"]}]}
    monkeypatch.setattr(online.httpx, "get", fake({"results": []}, ol))
    r = online.lookup("Thinking, Fast and Slow", "Daniel Kahneman")
    assert r["openlibrary"] == {"access": "borrowable", "url": "https://openlibrary.org/works/B",
                                "read_url": "https://openlibrary.org/works/B"}


def test_no_match(monkeypatch):
    monkeypatch.setattr(online.httpx, "get", fake({"results": []}, {"docs": []}))
    assert online.lookup("Python Crash Course", "Eric Matthes") == {"gutenberg": None, "openlibrary": None}


def test_error_gives_empty_and_is_not_cached(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(online.httpx, "get", boom)
    assert online.lookup("Meditations", "Marcus Aurelius") == {}
    calls = []
    monkeypatch.setattr(online.httpx, "get", fake(GUT, {"docs": []}, calls))
    assert online.lookup("Meditations", "Marcus Aurelius")["gutenberg"]
    assert calls


def test_cache_hit(monkeypatch):
    calls = []
    monkeypatch.setattr(online.httpx, "get", fake(GUT, {"docs": []}, calls))
    first = online.lookup("Meditations", "Marcus Aurelius")
    n = len(calls)
    online._mem.clear()  # force the disk path
    assert online.lookup("Meditations", "Marcus Aurelius") == first
    assert len(calls) == n


BODY = " ".join(["The quick brown fox jumps over the lazy dog."] * 40)
FIXTURE = f"""The Project Gutenberg eBook of A Tiny Book

Title: A Tiny Book

*** START OF THE PROJECT GUTENBERG EBOOK A TINY BOOK ***

CONTENTS

     CHAPTER I.
     CHAPTER II.

CHAPTER I.
THE BEGINNING OF THINGS.

{BODY}

Second paragraph of chapter one.

CHAPTER II.

{BODY} and this belongs to chapter two.

*** END OF THE PROJECT GUTENBERG EBOOK A TINY BOOK ***
License text that must never be shown.
"""


def test_extract_chapter_skips_toc_and_stops_at_next_chapter():
    r = online.extract_chapter(FIXTURE)
    assert r["title"] == "A Tiny Book"
    assert r["chapter_title"] == "Chapter I. The Beginning of Things."
    assert r["paragraphs"][-1] == "Second paragraph of chapter one."
    assert not any("chapter two" in p or "License" in p for p in r["paragraphs"])
    assert r["minutes"] >= 1


def test_extract_chapter_book_headings_and_cap():
    text = ("*** START OF THE PROJECT GUTENBERG EBOOK X ***\nCONTENTS\n\n FIRST BOOK\n\n SECOND BOOK\n\n"
            "THE FIRST BOOK\n\n" + "\n\n".join([BODY] * 100) + "\n\nTHE SECOND BOOK\n\nmore\n")
    r = online.extract_chapter(text)
    assert r["chapter_title"] == "The First Book"
    assert sum(len(p) for p in r["paragraphs"]) <= online.MAX_CHARS


def test_extract_chapter_none_without_sections():
    assert online.extract_chapter("*** START OF THE PROJECT GUTENBERG EBOOK X ***\nshort\n") is None


def test_chapter_fetch_and_cache(monkeypatch):
    calls = []

    def get(url, **kw):
        calls.append(url)
        r = Resp(None)
        r.text = FIXTURE
        return r
    monkeypatch.setattr(online.httpx, "get", get)
    a = online.chapter(99)
    assert a["source_url"].endswith("/ebooks/99")
    online._mem.clear()
    assert online.chapter(99) == a and len(calls) == 1
