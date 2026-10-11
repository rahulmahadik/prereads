"""catalog.enrich: fills only missing fields, in source order, survives failures, uses its cache.
No network: the source fetchers are monkeypatched and httpx.get is made to fail loudly."""
import httpx
import pytest

from app.integrations import catalog, sources
from app.core.models import Book


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(catalog, "ENRICH_DIR", tmp_path / "enrich")

    def no_network(*a, **k):
        raise AssertionError("network call in a test")

    monkeypatch.setattr(httpx, "get", no_network)


def _fake(monkeypatch, recs: dict, calls: list):
    def make(name):
        def fetch(title, author, isbn=None):
            calls.append(name)
            r = recs[name]
            if isinstance(r, Exception):
                raise r
            return dict(r)
        return fetch
    monkeypatch.setattr(sources, "FETCHERS", {n: make(n) for n in recs})


def _book(**kw):
    base = dict(id="9780000000001", title="Thinking, Fast and Slow", author="Daniel Kahneman",
                isbn="9780000000001", subjects=["Psychology"], pages=499, year=2011, ddc="153.4",
                cover_url="https://x/c.jpg", audience=["Adult"], summary="")
    base.update(kw)
    return Book(**base)


def test_fills_missing_summary_from_first_source_that_has_it(monkeypatch):
    calls: list = []
    _fake(monkeypatch, {"overdrive": {}, "openlibrary": {"summary": "From Open Library."},
                        "google": {"summary": "From Google."}}, calls)
    out = catalog.enrich(_book(), network=True)
    assert out.summary == "From Open Library."
    assert out.field_sources == {"summary": "openlibrary"}
    assert "google" not in calls          # stops at the first source with a value


def test_never_overwrites_existing_fields(monkeypatch):
    calls: list = []
    _fake(monkeypatch, {"overdrive": {"summary": "OD", "cover_url": "https://od/c.jpg", "audience": ["Children"]},
                        "openlibrary": {"pages": 10, "year": 1900, "ddc": "000", "subjects": ["Other"]},
                        "google": {}}, calls)
    nlb = _book(summary="NLB summary.", source="nlb")
    out = catalog.enrich(nlb, network=True)
    assert out.model_dump() == nlb.model_dump()
    assert calls == []                    # nothing missing: no source is asked

    thin = _book(summary="", cover_url=None, pages=None)
    out = catalog.enrich(thin, network=True)
    assert (out.summary, out.cover_url, out.pages) == ("OD", "https://od/c.jpg", 10)
    assert (out.audience, out.year, out.ddc, out.subjects) == (["Adult"], 2011, "153.4", ["Psychology"])
    assert thin.summary == "" and thin.pages is None   # the input book is not mutated


def test_survives_source_errors(monkeypatch):
    calls: list = []
    _fake(monkeypatch, {"overdrive": sources.SourceError("HTTP 429"), "openlibrary": RuntimeError("boom"),
                        "google": {"summary": "From Google.", "pages": 320}}, calls)
    out = catalog.enrich(_book(pages=None), network=True)
    assert out.summary == "From Google." and out.pages == 320
    assert out.field_sources == {"summary": "google", "pages": "google"}
    assert calls.count("openlibrary") == 1   # a failed source is not retried for the next field

    monkeypatch.setattr(catalog, "_enrich_cache_read", lambda *_: 1 / 0)
    b = _book()
    assert catalog.enrich(b, network=True) is b  # an unexpected error returns the book unchanged


def test_hits_the_cache_and_does_not_cache_failures(monkeypatch):
    calls: list = []
    _fake(monkeypatch, {"overdrive": {"summary": "OD summary."}, "openlibrary": sources.SourceError("down"),
                        "google": {}}, calls)
    first = catalog.enrich(_book(ddc=None), network=True)
    assert first.summary == "OD summary." and first.ddc is None
    assert catalog._enrich_path("9780000000001").exists()

    calls.clear()
    _fake(monkeypatch, {"overdrive": RuntimeError("must come from cache"), "openlibrary": {"ddc": "153.42"},
                        "google": {}}, calls)
    second = catalog.enrich(_book(ddc=None), network=True)
    assert second.summary == "OD summary."          # served from the disk cache
    assert second.ddc == "153.42"                   # the earlier failure was not cached, so it is retried
    assert calls == ["openlibrary"]

    calls.clear()
    third = catalog.enrich(_book(ddc=None), network=False)   # cache only (DEMO)
    assert (third.summary, third.ddc) == ("OD summary.", "153.42") and calls == []


def test_same_title_rejects_adaptations_and_summaries():
    assert sources.same_title("The Black Swan: The Impact of the Highly Improbable", "The Black Swan")
    assert not sources.same_title("Astrophysics for People in a Hurry", "Astrophysics for Young People in a Hurry")
    assert not sources.same_title("Sapiens", "Summary of Sapiens")
    assert not sources.same_title("Why We Sleep", "Why We Can't Sleep")
    assert sources.same_title("Gödel, Escher, Bach", "Godel, Escher, Bach: An Eternal Golden Braid")
    assert sources.same_title("Understanding Distributed Systems, Second Edition", "Understanding Distributed Systems")
    assert sources._surname("Gene Kim, Kevin Behr") == "kim" and sources._surname("Kahneman, Daniel") == "kahneman"


def test_overdrive_audience_mapping():
    adult = {"subjects": [{"name": "Psychology"}, {"name": "Nonfiction"}], "juvenileEligible": False}
    child = {"subjects": [{"name": "Juvenile Nonfiction"}], "juvenileEligible": True}
    teen = {"subjects": [{"name": "Young Adult Fiction"}], "youngAdultEligible": True}
    assert sources.overdrive_audience(adult) == []  # adult collection is not an audience signal
    assert sources.overdrive_audience(child) == ["Children"]
    assert sources.overdrive_audience(teen) == ["Young adult"]
    assert sources.overdrive_audience({}) == []
