from app.integrations import availability, catalog
from app.core.models import Book


def test_pick_ddc():
    assert catalog.pick_ddc(["153.4", "153.83", "153.42"]) == "153.4"
    assert catalog.pick_ddc(["332.6", "332.024", "658"]).startswith("332")
    assert catalog.pick_ddc([]) is None
    assert catalog.pick_ddc(None) is None


def test_openlibrary_ddc_uses_http_helper(monkeypatch):
    class R:
        def raise_for_status(self): pass
        def json(self): return {"docs": [{"title": "Thinking, Fast and Slow", "ddc": ["153.4", "153.83"]}]}
    monkeypatch.setattr(catalog.httpx, "get", lambda *a, **k: R())
    assert catalog.openlibrary_ddc("Thinking, Fast and Slow", "Daniel Kahneman") == "153.4"


def test_demo_call_number_uses_ddc():
    b = Book(id="x1", title="Some Unlisted Book", author="Daniel Kahneman", ddc="153.4")
    rows = availability.demo_availability(b)
    assert rows and all(r.call_number == "English 153.4 KAH" and r.demo for r in rows)


def test_demo_call_number_fallback_without_ddc():
    b = Book(id="x2", title="Some Unlisted Book", author="Daniel Kahneman")
    rows = availability.demo_availability(b)
    assert rows and all(r.call_number == "English 001.4 KAH" for r in rows)
