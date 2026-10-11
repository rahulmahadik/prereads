"""Deep discovery as a retrieval-augmented reranker: one model call orders the verified fast shortlist.

No network and no real model: llm.structured is patched in every test.
"""
import json

import pytest

from app.core import config
from app.core.models import Book, Readiness
from app.services import discover
from app.services.discover import DiscoverRequest, Need, Proposal, Proposed, RerankPick, RerankReply

QUERY = "I want to understand investing but I only have 2 weeks"


@pytest.fixture
def ai_on(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "DEMO", True)                    # no catalogue pages: the rerank path alone
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(discover, "RERANK_DIR", tmp_path / "rerank")
    discover._RERANKS.clear()
    discover._PROPOSALS.clear()
    discover._VERIFIED.clear()
    yield
    discover._RERANKS.clear()
    discover._PROPOSALS.clear()


def _candidates(text: str = QUERY) -> list[dict]:
    """The catalogue entries the deep phase hands the model: the fast order, top RERANK_K."""
    fast = discover.discover(DiscoverRequest(text=text, mode="fast", limit=50))
    by_id = {e["id"]: e for e in discover._catalogue()}
    cands = [by_id[r.id] for r in fast.results[: discover.RERANK_K]]
    assert len(cands) >= 6, "the demo catalogue should match this request"
    return cands


class FakeModel:
    def __init__(self, reply=None, proposal=None):
        self.reply, self.proposal, self.calls = reply, proposal, []

    def __call__(self, schema, system, user, **k):
        self.calls.append({"schema": schema.__name__, "system": system, "user": user, **k})
        if schema is RerankReply:
            return self.reply
        if schema is Proposal:
            return self.proposal
        raise AssertionError(f"unexpected model call {schema.__name__}")


def test_rerank_drops_unknown_ids_and_keeps_the_model_order(ai_on, monkeypatch):
    cands = _candidates()
    long = "This one is about investing and it is pitched for a newcomer who has two weeks and wants plain words only please, with no jargon at all"
    fake = FakeModel(RerankReply(topics=["investing"], level=1, max_hours=10, picks=[
        RerankPick(id="b3", reason="**Plain** and short."),
        RerankPick(id="b99", reason="Not a candidate."),
        RerankPick(id="Invented Book", reason="Never shown."),
        RerankPick(id="1", reason="Bare number means b1."),
        RerankPick(id="b3", reason="Repeat."),
        RerankPick(id=cands[4]["id"], reason=long),
    ]))
    monkeypatch.setattr(discover.llm, "structured", fake)
    rr = discover.rerank(discover.heuristic_need(QUERY), QUERY, cands)
    assert [i for i, _ in rr.picks] == [cands[2]["id"], cands[0]["id"], cands[4]["id"]]
    assert rr.picks[0][1] == "Plain and short."
    assert len(rr.picks[2][1].split()) <= discover.RERANK_REASON_WORDS and rr.picks[2][1].endswith("…")
    assert rr.need.level == 1 and rr.need.max_hours == 10 and rr.need.topics == ["investing"]
    call = fake.calls[0]
    assert call["temperature"] == 0.2
    sent = json.loads(call["user"])
    assert sent["REQUEST"] == QUERY and len(sent["CANDIDATES"]) == len(cands[: discover.RERANK_K])
    for c in sent["CANDIDATES"]:                                  # compact: no full summaries
        assert set(c) == {"id", "title", "author", "level", "hours", "about", "blurb"}
        assert len(c["blurb"]) <= 161 and len(c["about"]) <= 5


def test_rerank_cache_hits_skip_the_model(ai_on, monkeypatch):
    cands = _candidates()
    fake = FakeModel(RerankReply(topics=["investing"], picks=[RerankPick(id="b2", reason="Fits."), RerankPick(id="b1", reason="Also.")]))
    monkeypatch.setattr(discover.llm, "structured", fake)
    need = discover.heuristic_need(QUERY)
    first = discover.rerank(need, QUERY, cands)
    again = discover.rerank(need, "  i want to understand INVESTING but i only have 2 weeks? ", cands)   # same normalized query
    assert len(fake.calls) == 1 and again.cached and again.picks == first.picks
    discover._RERANKS.clear()                                      # a restart: the disk copy answers
    disk = discover.rerank(need, QUERY, cands)
    assert len(fake.calls) == 1 and disk.cached and disk.picks == first.picks
    assert list((discover.RERANK_DIR).glob("*.json"))
    discover.rerank(need, QUERY, cands, lang="zh")                 # another language is another answer
    discover.rerank(need, QUERY, cands[:-1])                       # so is another shortlist
    assert len(fake.calls) == 3


def test_rerank_passes_the_language_instruction(ai_on, monkeypatch):
    cands = _candidates()
    fake = FakeModel(RerankReply(topics=["投资"], picks=[RerankPick(id="b1", reason="简单易读。")]))
    monkeypatch.setattr(discover.llm, "structured", fake)
    rr = discover.rerank(discover.heuristic_need(QUERY), QUERY, cands, lang="zh")
    assert "Simplified Chinese" in fake.calls[0]["system"] and fake.calls[0]["system"].startswith(discover.RERANK_SYSTEM)
    assert rr.picks[0][1] == "简单易读。"
    assert rr.need.topics == discover.heuristic_need(QUERY).topics   # non-ASCII topics would blind the keyword scorer
    discover.rerank(discover.heuristic_need(QUERY), QUERY, cands, lang="en")
    assert fake.calls[1]["system"] == discover.RERANK_SYSTEM


def test_rerank_is_off_without_the_model_or_candidates(ai_on, monkeypatch):
    fake = FakeModel()
    monkeypatch.setattr(discover.llm, "structured", fake)
    assert discover.rerank(Need(), QUERY, []) is None
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    assert discover.rerank(Need(), QUERY, _candidates()) is None
    assert fake.calls == []


def test_deep_falls_back_to_the_fast_order_when_the_model_returns_none(ai_on, monkeypatch):
    fake = FakeModel(reply=None)
    monkeypatch.setattr(discover.llm, "structured", fake)
    fast = discover.discover(DiscoverRequest(text=QUERY, mode="fast", limit=30))
    deep = discover.discover(DiscoverRequest(text=QUERY, mode="deep", limit=30))
    assert [r.id for r in deep.results] == [r.id for r in fast.results]
    assert not any(r.ai_rank for r in deep.results)
    assert deep.engine == "heuristic"
    assert [c["schema"] for c in fake.calls] == ["RerankReply"]    # a failed model is not asked again for proposals
    assert "rerank" in deep.timings_ms


def test_deep_rerank_orders_the_list_with_reasons_in_one_call(ai_on, monkeypatch):
    cands = _candidates()
    fake = FakeModel(RerankReply(topics=["investing"], level=1, max_hours=10, picks=[
        RerankPick(id="b5", reason="Short and plain, made for your two weeks."),
        RerankPick(id="b2", reason="A gentle start on index funds."),
        RerankPick(id="b77", reason="Unknown: dropped."),
        RerankPick(id="b7", reason="Explains risk without maths."),
    ]))
    monkeypatch.setattr(discover.llm, "structured", fake)
    r = discover.discover(DiscoverRequest(text=QUERY, mode="deep", limit=30))
    assert [c["schema"] for c in fake.calls] == ["RerankReply"]    # one call: need + order; no proposals
    assert r.engine == "llm" and r.ai == "ok"
    top = r.results[:3]
    assert [x.id for x in top] == [cands[4]["id"], cands[1]["id"], cands[6]["id"]]
    assert [x.ai_rank for x in top] == [1, 2, 3]
    assert top[0].why == "Short and plain, made for your two weeks."
    assert not any(x.ai_rank for x in r.results[3:])
    assert r.need.level == 1 and any(c.id == "level:1" for c in r.chips)
    assert {"need", "embed", "score", "rerank", "rescore", "total"} <= set(r.timings_ms)
    assert "propose" not in r.timings_ms
    # a filter toggle re-runs deep: a filtered shortlist is a new question, the same one is cached
    discover.discover(DiscoverRequest(text=QUERY, mode="deep", limit=30))
    assert len(fake.calls) == 1


def test_deep_rerank_asks_for_new_titles_when_few_fit(ai_on, monkeypatch):
    fake = FakeModel(
        RerankReply(topics=["investing"], picks=[RerankPick(id="b1", reason="The one that fits.")]),
        Proposal(need=Need(summary="investing", topics=["investing"]), books=[
            Proposed(title="A Totally New Investing Book", author="Ann Author", why="Plain and short."),
            Proposed(title="Invented Nonsense", author="Nobody", why="Should be dropped."),
        ]),
    )
    monkeypatch.setattr(discover.llm, "structured", fake)
    monkeypatch.setattr(discover, "resolve", lambda title, author="": None if title == "Invented Nonsense" else Book(
        id="ol:new-investing", title=title, author=author, subjects=["Investing"], summary="", source="openlibrary"))
    monkeypatch.setattr(discover, "score_readiness", lambda b: (Readiness(level=1, hours=5, assumed_concepts=[], style_tags=[], one_line=""), "llm"))
    r = discover.discover(DiscoverRequest(text=QUERY, mode="deep", limit=50))
    assert [c["schema"] for c in fake.calls] == ["RerankReply", "Proposal"]
    assert r.results[0].ai_rank == 1 and r.results[0].why == "The one that fits."
    titles = {x.title: x for x in r.results}
    assert titles["A Totally New Investing Book"].ai_pick and "Invented Nonsense" not in titles
    assert "propose" in r.timings_ms


def test_rerank_uses_the_fast_chat_tier_and_never_invents_a_time_budget(ai_on, monkeypatch):
    cands = _candidates("investing for a beginner")
    fake = FakeModel(RerankReply(topics=["investing"], level=1, max_hours=19, picks=[RerankPick(id="b1", reason="Fits.")]))
    monkeypatch.setattr(discover.llm, "structured", fake)
    rr = discover.rerank(discover.heuristic_need("investing for a beginner"), "investing for a beginner", cands)
    assert fake.calls[0]["kind"] == "chat"
    assert rr.need.level == 1 and rr.need.max_hours is None          # the request never mentions time


def test_a_slow_model_keeps_the_fast_order_within_the_budget(ai_on, monkeypatch):
    import threading
    import time

    gate = threading.Event()

    def slow(schema, system, user, **k):
        gate.wait(5)                                              # the model is busy with someone else
        return RerankReply(topics=["investing"], picks=[RerankPick(id="b2", reason="Late.")])

    monkeypatch.setattr(discover.llm, "structured", slow)
    monkeypatch.setattr(discover, "RERANK_BUDGET_S", 0.2)
    fast = discover.discover(DiscoverRequest(text=QUERY, mode="fast", limit=30))
    t = time.perf_counter()
    deep = discover.discover(DiscoverRequest(text=QUERY, mode="deep", limit=30))
    assert time.perf_counter() - t < 1.5
    assert deep.ai == "busy" and deep.engine == "heuristic"
    assert [r.id for r in deep.results] == [r.id for r in fast.results]
    gate.set()                                                    # the abandoned call still lands in the cache
    for _ in range(50):
        if discover._RERANKS:
            break
        time.sleep(0.02)
    again = discover.discover(DiscoverRequest(text=QUERY, mode="deep", limit=30))
    assert again.ai == "ok" and again.results[0].ai_rank == 1


def test_old_propose_path_is_kept_behind_the_flag(ai_on, monkeypatch):
    fake = FakeModel(proposal=Proposal(need=Need(summary="investing", topics=["investing"]), books=[]))
    monkeypatch.setattr(discover.llm, "structured", fake)
    monkeypatch.setattr(discover, "DEEP_STRATEGY", "propose")
    r = discover.discover(DiscoverRequest(text="investing", mode="deep"))
    assert [c["schema"] for c in fake.calls] == ["Proposal"] and not any(x.ai_rank for x in r.results)
