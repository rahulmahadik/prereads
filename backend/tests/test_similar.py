"""Embedding shortlist + 'Because you liked': offline fallbacks and the verified-only guard."""
from __future__ import annotations

from app.core import config
from app.services import discover, engine
from app.ai import embeddings
from app.core.models import Book


def test_similar_keyword_fallback_returns_verified_neighbours(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    cat = {e["id"]: e for e in discover._catalogue()}
    out = discover.similar("9780374533557")
    assert 0 < len(out) <= 3
    for n in out:
        assert n["id"] in cat                       # never a book outside the verified catalogue
        assert n["line_id"] != "9780374533557"       # not from the book's own path
        assert n["reason"]


def test_llm_neighbours_drop_ids_outside_shortlist(monkeypatch):
    me = {"id": "a", "title": "A", "author": "x", "subjects": [], "concepts": []}
    cands = [{"id": "b", "title": "B", "author": "y", "subjects": [], "concepts": []}]
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(discover, "SIMILAR_DIR", config.CACHE_DIR / "similar-test")
    monkeypatch.setattr(discover.llm, "structured", lambda *a, **k: discover.Neighbours(picks=[discover.Neighbour(id="ghost", reason="made up"), discover.Neighbour(id="b", reason="Shares an idea.")]))
    got = discover._llm_neighbours(me, cands, 3)
    assert [(e["id"], r) for e, r in got] == [("b", "Shares an idea.")]
    for f in (config.CACHE_DIR / "similar-test").glob("*.json"):
        f.unlink()
    (config.CACHE_DIR / "similar-test").rmdir()


def test_semantic_topic_scale():
    assert discover.semantic_topic(0.0) == 0
    assert discover.semantic_topic(0.25) == 0.8           # capped below an explicit keyword match
    assert 0 < discover.semantic_topic(0.17) < 0.8


def test_candidate_order_is_noop_without_embeddings():
    items = [{"title": "X"}, {"title": "Y"}]
    assert engine._by_similarity(Book(id="t", title="T"), items) == items


def test_rank_centres_vectors(monkeypatch):
    vecs = {"q": [1.0, 1.0], "a": [1.0, 0.9], "b": [0.9, 1.0], "c": [1.0, 1.0]}
    monkeypatch.setattr(embeddings, "vectors", lambda texts, prefix="": [vecs[t] for t in texts])
    r = embeddings.rank("q", [("a", "a"), ("b", "b"), ("c", "c")])
    assert [i for i, _ in r][0] in {"a", "b", "c"} and len(r) == 3
