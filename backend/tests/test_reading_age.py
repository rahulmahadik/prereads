from app import config, reading_age
from app.models import Book, Readiness


def rd(level):
    return Readiness(level=level, hours=5)


def book(**kw):
    return Book(id=kw.pop("id", "b1"), title="T", author="A", **kw)


def test_juvenile_subject_is_children():
    r = reading_age.estimate(book(subjects=["Juvenile fiction"]), rd(4))
    assert r["label"].startswith("Children") and r["source"] == "estimated" and r["min_age"] == 8


def test_adult_audience_is_adult_catalogue():
    r = reading_age.estimate(book(audience=["Adult"]), rd(1))
    assert r == {"label": "Adult", "min_age": 18, "source": "catalogue"}


def test_young_adult_audience_is_teen():
    assert reading_age.estimate(book(audience=["Young adult"]), rd(5))["label"] == "Teen"


def test_level_estimates():
    assert reading_age.estimate(book(), rd(1))["label"] == "Reading age 12+"
    assert reading_age.estimate(book(pages=700), rd(2))["label"] == "Reading age 15+"
    assert reading_age.estimate(book(), rd(3))["label"] == "Reading age 15+"
    assert reading_age.estimate(book(), rd(5))["label"] == "Adult"


def test_llm_result_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(reading_age, "_llm_min_age", lambda b: calls.append(1) or 14)
    b = book(id="x1")
    first = reading_age.estimate(b, rd(2), use_llm=True)
    second = reading_age.estimate(b, rd(2), use_llm=True)
    assert first == second and first["source"] == "estimated" and first["min_age"] == 14
    assert len(calls) == 1 and (tmp_path / "reading_age" / "x1.json").exists()


def test_age_chip_filters():
    from app.discover import FilterChip, Recommendation, apply_filters
    def rec(i, a):
        return Recommendation(id=i, line_id=i, is_target=True, title=i, author="", category="", level=1, hours=1, why="", fit=1, status="", available_at=[], hot_at=[], before_count=0, min_age=a)
    rs = [rec("k", 8), rec("t", 12), rec("a", 18)]
    chip = lambda v: [FilterChip(id=f"age:{v}", label=v, kind="age", value=v, on=True)]
    assert [r.id for r in apply_filters(rs, chip("child"))] == ["k"]
    assert [r.id for r in apply_filters(rs, chip("teen"))] == ["k", "t"]
    assert len(apply_filters(rs, chip("adult"))) == 3
