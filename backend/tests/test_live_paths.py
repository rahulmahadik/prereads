"""Exercise the live-mode code paths without network: stub the LLM and NLB
clients and make sure parsing, judging, rules and route assembly hold up."""
from __future__ import annotations

import pytest

from app import ask as ask_mod
from app import availability as av
from app import catalog, config, engine, llm
from app.models import AskRequest, Book, CandidateList, Judgment, Readiness, ScanResult


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(config, "DEMO", False)
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "nlb_enabled", lambda: True)

    # ---- fake LLM ----
    def fake_readiness(book: Book):
        lvl = 2 if "Irrational" in book.title else 4
        return Readiness(level=lvl, hours=8, assumed_concepts=["probability"], style_tags=["narrative"], one_line="ok")

    def fake_candidates(target: Book):
        return CandidateList(
            before=[{"title": "Predictably Irrational", "author": "Dan Ariely", "why": "gentler"},
                    {"title": "Ghost Book", "author": "Nobody", "why": "invented"}],
            after=[{"title": "Noise", "author": "Daniel Kahneman", "why": "sequel"}],
        )

    def fake_judge(a, b, ra, rb):
        if ra and rb and ra.level < rb.level:
            return Judgment(relation="prepares_for", confidence=0.9, reason="Covers the biases first.")
        return Judgment(relation="follows", confidence=0.8, reason="Goes deeper.")

    monkeypatch.setattr(llm, "readiness", fake_readiness)
    monkeypatch.setattr(llm, "candidates", fake_candidates)
    monkeypatch.setattr(llm, "judge", fake_judge)
    monkeypatch.setattr(llm, "ask", lambda route_json, q: "Grounded answer.")
    monkeypatch.setattr(llm, "scan", lambda data, mime="image/jpeg": ScanResult(title="Noise", author="Daniel Kahneman", confidence=0.9))

    # ---- fake NLB, in the real Catalogue v2 shapes (TitleSummary with records[], Item with location/status objects) ----
    def fake_search(self, title, author="", limit=5):
        if "Ghost" in title:
            return []
        isbn = "9780000000001" if "Thinking" in title else "9780000000002" if "Irrational" in title else "9780000000003"
        return [{
            "title": f"{title} / {author}.", "author": author, "coverUrl": {"small": None, "medium": "https://x/cover.jpg", "large": None},
            "records": [{"brn": 123, "isbns": [f"{isbn[:-1]}{(int(isbn[-1]) + 5) % 10} (pbk)", isbn], "publishDate": "2011", "subjects": ["Psychology"],
                         "physicalDescription": ["499 pages ; 24 cm"], "summary": None, "availability": True, "activeReservationsCount": 3,
                         "audience": ["Adult"], "language": ["English"]}],
        }]

    def fake_search_isbn(self, isbn):
        return []

    def fake_details(self, brn=None, isbn=None):
        return {"brn": 123, "title": "Thinking, fast and slow", "author": "Daniel Kahneman", "isbns": ["9780000000001"],
                "summary": ["A summary."], "subjects": ["Psychology", "Decision making"], "physicalDescription": ["499 pages"],
                "activeReservationsCount": 3, "publishDate": "2011"}

    def fake_availability(self, brn=None, isbn=None):
        return [
            {"callNumber": "English 153.4 KAH", "formattedCallNumber": "English 153.4 KAH", "location": {"code": "BIPL", "name": "Bishan Public Library"}, "status": {"name": "Available", "code": "A"}},
            {"callNumber": "English 153.4 KAH", "formattedCallNumber": "English 153.4 KAH", "location": {"code": "BIPL", "name": "Bishan Public Library"}, "status": {"name": "On Loan", "code": "L"}},
            {"callNumber": "English 153.4 KAH", "formattedCallNumber": "English 153.4 KAH", "location": {"code": "TRL", "name": "Tampines Regional Library"}, "status": {"name": "In Transit", "code": "I"}},
        ]

    def fake_trends(self, location=None, limit=50):
        return [{"title": "Thinking, fast and slow", "author": "Daniel Kahneman", "isbns": ["9780000000001"], "checkoutsCount": 42, "fiction": False, "ageLevel": "Adult", "language": "English"}] if location == "BIPL" else []

    monkeypatch.setattr(catalog.NLBClient, "enabled", lambda self: True)
    monkeypatch.setattr(catalog.NLBClient, "search", fake_search)
    monkeypatch.setattr(catalog.NLBClient, "search_isbn", fake_search_isbn)
    monkeypatch.setattr(catalog.NLBClient, "details", fake_details)
    monkeypatch.setattr(catalog.NLBClient, "availability", fake_availability)
    monkeypatch.setattr(catalog.NLBClient, "trends", fake_trends)
    monkeypatch.setattr(catalog, "openlibrary_search", lambda title, author="": None)
    return True


def test_live_route_builds_and_drops_unverified(live):
    seed = {"title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "level": 4, "hours": 16}
    route = engine.build_route(seed)
    titles = [s.book.title for s in route.stops]
    assert "Predictably Irrational" in titles[0], (titles, route.notes)
    assert "Ghost Book" not in " ".join(titles)
    assert any("unverified" in n for n in route.notes)
    assert route.engine == "llm"
    target = next(s for s in route.stops if s.role == "target")
    assert target.book.source == "nlb" and target.book.isbn in ("9780000000001", "9780000000006")
    assert target.book.summary == "A summary."
    assert target.book.pages == 499 and target.book.year == 2011 and target.book.cover_url == "https://x/cover.jpg"
    assert target.book.reservations == 3 and target.book.audience == ["Adult"]


def test_live_availability_aggregates_per_branch(live):
    b = Book(id="9780000000001", title="Thinking, Fast and Slow", author="Daniel Kahneman", isbn="9780000000001", brn="123")
    rows = av.get_availability(b)
    bishan = next(r for r in rows if r.branch_code == "BIPL")
    assert (bishan.available, bishan.total, bishan.demo) == (1, 2, False)
    tamp = next(r for r in rows if r.branch_code == "TRL")
    assert (tamp.available, tamp.total) == (0, 1)
    d = av.get_demand(b, rows)
    assert d.hot_branches == ["Bishan Public Library"] and d.demo is False
    assert d.reservations == 0  # no reservations known on this bare Book


def test_live_ask_and_scan(live):
    seed = {"title": "Thinking, Fast and Slow", "author": "Daniel Kahneman", "level": 4, "hours": 16}
    route = engine.build_route(seed)
    res = ask_mod.answer(route, AskRequest(target_id=route.target_id, intent="why_before"))
    assert res.engine == "llm" and res.answer == "Grounded answer."
    s = llm.scan(b"fake", "image/jpeg")
    assert s and s.title == "Noise"


def test_title_guard_rejects_wrong_book():
    assert catalog.title_matches("Predictably Irrational", "Predictably irrational : the hidden forces / Dan Ariely.")
    assert not catalog.title_matches("Predictably Irrational", "Thinking, fast and slow / Daniel Kahneman.")


def test_demo_mode_never_calls_network(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    monkeypatch.setattr(config, "nlb_enabled", lambda: False)
    seed = engine.seeds()[0]
    route = engine.build_route(seed)
    assert route.engine == "seed"
    assert all(a.demo for s in route.stops for a in s.availability)
