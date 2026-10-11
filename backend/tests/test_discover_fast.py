"""Two-phase discovery: fast makes no model or network call; deep still adds verified model picks."""
import time

import pytest

from app.integrations import catalog
from app.core import config
from app.services import discover
from app.ai import llm
from app.services.discover import DiscoverRequest, Need, Proposal, Proposed
from app.core.models import Book, Readiness


CALLED: list[str] = []


def _boom(*a, **k):
    CALLED.append(repr(a[:1]))
    raise AssertionError("fast mode must not call this")


@pytest.fixture
def no_model_no_network(monkeypatch):
    CALLED.clear()
    monkeypatch.setattr(config, "DEMO", False)                 # live mode: the slow paths would run if reachable
    monkeypatch.setattr(config, "llm_enabled", lambda: True)   # even with the AI "on", fast must not ask it
    monkeypatch.setattr(llm, "structured", _boom)
    monkeypatch.setattr(catalog, "openlibrary_search", _boom)
    monkeypatch.setattr(catalog, "openlibrary_search_many", _boom)
    monkeypatch.setattr(discover, "openlibrary_search_many", _boom)
    monkeypatch.setattr(discover, "resolve", _boom)
    monkeypatch.setattr(discover, "score_readiness", _boom)
    monkeypatch.setattr(discover.nlb(), "_get", _boom)
    yield
    assert not CALLED, f"fast mode reached the model or the network: {CALLED}"


@pytest.mark.parametrize("text", ["investing", "universe", "I want to understand investing but I only have 2 weeks"])
def test_fast_mode_no_llm_no_network_and_quick(no_model_no_network, text):
    t = time.perf_counter()
    r = discover.discover(DiscoverRequest(text=text, mode="fast"))
    took = time.perf_counter() - t
    assert took < 1.0, f"fast discovery took {took:.2f}s"
    assert r.engine == "fast"
    assert r.results and all(0 < x.fit <= 1 for x in r.results)
    assert not any(x.ai_pick for x in r.results)
    assert r.deep == "ai"                                       # tells the UI a deep pass is worth running
    assert "total" in r.timings_ms


def test_fast_is_the_default_and_pages(no_model_no_network):
    q = {"text": "psychology economics history science", "limit": 5}
    p1 = discover.discover(DiscoverRequest(**q))
    assert p1.engine == "fast" and len(p1.results) == 5 and p1.has_more
    p2 = discover.discover(DiscoverRequest(**q, offset=5))
    assert {x.id for x in p1.results}.isdisjoint({x.id for x in p2.results})


def test_fast_keeps_a_chip_only_deep_generated(no_model_no_network):
    # The reader turned on "Level 2 or easier" from the deep chips; the fast re-run must still apply it.
    r = discover.discover(DiscoverRequest(text="investing", filters=["level:2"]))
    chip = next(c for c in r.chips if c.id == "level:2")
    assert chip.on and all(x.level <= 2 for x in r.results)
    assert discover.chip_from_id("level:9") is None and discover.chip_from_id("nonsense") is None


def test_fast_slow_embeddings_fall_back_to_keywords(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(discover, "FAST_EMBED_BUDGET_S", 0.05)
    monkeypatch.setattr(discover, "_rank_fast", lambda *a, **k: time.sleep(0.5) or [])
    t = time.perf_counter()
    r = discover.discover(DiscoverRequest(text="investing"))
    assert time.perf_counter() - t < 0.4
    assert r.results                                            # keyword path still answers


def test_deep_mode_adds_verified_model_picks(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)                   # no catalogue search pages; proposals still checked
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    discover._PROPOSALS.clear()
    discover._VERIFIED.clear()
    cat = discover._catalogue()
    cached = next(e for e in cat if "invest" in e["title"].lower()) if any("invest" in e["title"].lower() for e in cat) else cat[0]
    calls = []

    def fake_structured(schema, system, user, **k):
        calls.append(schema.__name__)
        assert schema is Proposal
        return Proposal(
            need=Need(summary="investing for a beginner", topics=["investing"], level=1, max_hours=10),
            books=[
                Proposed(title="A Totally New Investing Book", author="Ann Author", why="Plain and short."),
                Proposed(title=cached["title"], author=cached["author"], why="Already on a reading path."),
                Proposed(title="Invented Nonsense", author="Nobody", why="Should be dropped."),
            ],
        )

    def fake_resolve(title, author=""):
        if title == "Invented Nonsense":
            return None                                         # not in the catalogue: never shown
        return Book(id="ol:new-investing", title=title, author=author, subjects=["Investing"], summary="", source="openlibrary")

    monkeypatch.setattr(discover.llm, "structured", fake_structured)
    monkeypatch.setattr(discover, "resolve", fake_resolve)
    monkeypatch.setattr(discover, "score_readiness", lambda b: (Readiness(level=1, hours=5, assumed_concepts=[], style_tags=[], one_line=""), "llm"))
    # strategy="propose": the old deep path (new titles first), kept behind a flag; the rerank path is in test_rerank.py
    r = discover.discover(DiscoverRequest(text="investing for a beginner", mode="deep", limit=50, strategy="propose"))
    assert r.engine == "llm" and r.deep is None
    titles = {x.title: x for x in r.results}
    assert "A Totally New Investing Book" in titles and titles["A Totally New Investing Book"].ai_pick
    assert "Invented Nonsense" not in titles
    assert titles[cached["title"]].ai_pick                      # a proposed book already in the catalogue is marked too
    assert r.need.level == 1 and any(c.id == "level:1" for c in r.chips)
    # A re-run for the same request (a filter toggle) reuses the model's answer.
    discover.discover(DiscoverRequest(text="investing for a beginner", mode="deep", filters=["hours:10"], strategy="propose"))
    assert calls == ["Proposal"]


def test_api_mode_field(monkeypatch):
    from fastapi.testclient import TestClient

    from app.main import app

    monkeypatch.setattr(config, "DEMO", True)
    c = TestClient(app)
    fast = c.post("/api/discover", json={"text": "universe", "mode": "fast"}).json()
    assert fast["engine"] == "fast" and fast["results"]
    deep = c.post("/api/discover", json={"text": "universe", "mode": "deep"}).json()
    assert deep["engine"] == "heuristic"                        # AI off in tests: deep is the old heuristic path
    assert c.post("/api/discover", json={"text": "universe", "mode": "slow"}).status_code == 422


def test_nonsense_gets_an_honest_empty_list_and_no_invented_time_chip(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    # nonsense: no keyword hit, and a centred similarity under the floor is not evidence
    monkeypatch.setattr(discover, "_shortlist", lambda need, cat, budget: ({e["id"]: 0.16 for e in cat}, "on"))
    r = discover.discover(DiscoverRequest(text="asdfgh"))
    assert r.results == [] and r.total == 0
    assert not any(c.kind == "hours" for c in r.chips)
    assert discover.semantic_topic(0.16) == 0 and discover.semantic_topic(0.2) > 0


def test_time_chip_only_when_the_reader_mentions_time(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    assert not any(c.kind == "hours" for c in discover.discover(DiscoverRequest(text="investing")).chips)
    chips = discover.discover(DiscoverRequest(text="investing but I only have 2 weeks")).chips
    assert any(c.id == "hours:10" for c in chips)
    assert discover.mentions_time("something for this weekend") and discover.mentions_time("我只有两周")
    assert not discover.mentions_time("Is AI dangerous for humanity?")


def test_blurb_strips_html_and_entities():
    raw = "<strong>A former Wall Street quant</strong> sounds an alarm on the mathematical models that pervade modern life &amp; threaten to rip apart our social fabric.<br/>"
    b = discover.blurb(raw)
    assert b.startswith("A former Wall Street quant sounds") and "<" not in b and "&amp;" not in b and "& threaten" in b
    assert "<" not in discover.blurb("&lt;p&gt;An escaped paragraph that still needs its tags removed before the card shows it.&lt;/p&gt;")
