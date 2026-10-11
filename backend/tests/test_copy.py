"""Reader-facing wording from the server: Ask templates (plurals, honest time budget, lang)."""
from __future__ import annotations

from app.core.models import AskRequest, Book, Readiness, Route, Stop
from app.services import ask


def _stop(role, title, hours, level):
    return Stop(role=role, order=0, book=Book(id=title, title=title, author="A"),
                readiness=Readiness(level=level, hours=hours), why="it sets up the ideas", confidence=0.9)


def _route(target_hours=8):
    stops = [_stop("before", "Easy", 4, 1), _stop("before", "Middle", 6, 2), _stop("target", "Goal", target_hours, 4)]
    return Route(target_id="Goal", stops=stops, generated_at="", engine="seed")


def _budget(route, weeks, lang=None):
    return ask._template(route, AskRequest(target_id="Goal", intent="time_budget", weeks=weeks, lang=lang))


def test_time_budget_plural_and_fit():
    one = _budget(_route(), 1).answer
    assert "week(s)" not in one and "~" not in one and " h)" not in one
    two = _budget(_route(), 2).answer                      # 10 h: Goal (8) is reserved, nothing else fits
    assert two == "With 2 weeks at about 5 hours a week, you can read Goal (about 8 hours). Leave Easy and Middle for later."
    three = _budget(_route(), 3)                           # 15 h: Easy (4) fits beside Goal, Middle (6) does not
    assert "you can read Easy and Goal (about 12 hours). Leave Middle for later." in three.answer
    assert three.adjusted_stop_ids == ["Easy", "Goal"]


def test_time_budget_never_claims_a_fit_when_your_book_alone_is_over():
    r = _budget(_route(target_hours=14), 1)
    assert r.answer.startswith("Your book alone runs past 1 week at about 5 hours a week: it needs about 14 hours.")
    assert "you can read" not in r.answer and "Start with Easy" in r.answer


def test_templates_follow_lang():
    assert "周" in _budget(_route(), 2, "zh").answer
    assert "minggu" in _budget(_route(), 2, "ms").answer
    assert "வாரங்களில்" in _budget(_route(), 2, "ta").answer
    why = ask._template(_route(), AskRequest(target_id="Goal", intent="why_before")).answer
    assert why.startswith("Read Easy first: it sets up the ideas.")
    lp = ask._template(_route(), AskRequest(target_id="Goal", intent="large_print", lang="ms")).answer
    assert "demo" not in lp and "PreReads" in lp
