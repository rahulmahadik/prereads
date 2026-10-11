import httpx
import pytest

from app import digital


def _item(kind, title="Thinking, Fast and Slow", owned=100, avail=16, holds=0, author="Daniel Kahneman", rid="abc"):
    return {"type": {"id": kind}, "title": title, "ownedCopies": owned, "availableCopies": avail,
            "holdsCount": holds, "reserveId": rid, "creators": [{"name": author, "role": "Author"}]}


class Resp:
    def __init__(self, items=None, status=200):
        self.items, self.status = items or [], status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("x", request=None, response=None)

    def json(self):
        return {"items": self.items}


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(digital, "CACHE_DIR", tmp_path)
    digital._mem.clear()


def test_parsed(monkeypatch):
    monkeypatch.setattr(digital.httpx, "get", lambda *a, **k: Resp([
        _item("ebook", owned=5, avail=2), _item("audiobook", owned=3, avail=0, holds=3, rid="zz"),
        _item("ebook", title="Something Else Entirely")]))
    d = digital.lookup("Thinking, Fast and Slow", "Daniel Kahneman")
    assert d["live"] and d["source"] == "overdrive"
    assert d["ebook"]["available"] == 2 and d["ebook"]["owned"] == 5
    assert d["audiobook"]["holds"] == 3 and d["audiobook"]["url"].endswith("/media/zz")


def test_no_match(monkeypatch):
    monkeypatch.setattr(digital.httpx, "get", lambda *a, **k: Resp([_item("ebook", title="Cooking for One")]))
    d = digital.lookup("Thinking, Fast and Slow", "Daniel Kahneman")
    assert d["live"] and d["ebook"] is None and d["audiobook"] is None


def test_error(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(digital.httpx, "get", boom)
    d = digital.lookup("Dune", "Frank Herbert")
    assert d["live"] is False and "nlb.overdrive.com/search" in d["search_url"]
    monkeypatch.setattr(digital.httpx, "get", lambda *a, **k: Resp(status=500))
    assert digital.lookup("Dune 2")["live"] is False


def test_cache_hit(monkeypatch):
    calls = []
    def fake(*a, **k):
        calls.append(1)
        return Resp([_item("ebook")])
    monkeypatch.setattr(digital.httpx, "get", fake)
    digital.lookup("Thinking, Fast and Slow", "Daniel Kahneman")
    digital.lookup("Thinking, Fast and Slow", "Daniel Kahneman")
    digital._mem.clear()  # disk cache still serves
    digital.lookup("Thinking, Fast and Slow", "Daniel Kahneman")
    assert len(calls) == 1
