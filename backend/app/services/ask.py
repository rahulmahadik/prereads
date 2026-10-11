"""Grounded questions about one reading path (why_before, time_budget, large_print, free).

The model is given only a brief of the cached route, so its answer is grounded in the stops
already on it; with AI off, a template answers from the same data.

Layer: services. Served by api/routes_paths.py (/api/ask).
"""
from __future__ import annotations

import json

from ..core import config
from ..ai import llm
from ..core.models import AskRequest, AskResponse, Route


def _route_brief(route: Route) -> str:
    rows = []
    for s in route.stops:
        best = max(s.availability, key=lambda a: a.available, default=None)
        where = f"{best.branch} ({best.available} of {best.total} in)" if best else "no copies listed"
        rows.append({
            "role": s.role, "order": s.order, "id": s.book.id, "title": s.book.title, "author": s.book.author,
            "level": s.readiness.level, "hours": s.readiness.hours, "why": s.why,
            "assumes": s.readiness.assumed_concepts, "where": where, "hot_at": s.demand.hot_branches,
        })
    return json.dumps(rows, ensure_ascii=False)


def _template(route: Route, req: AskRequest) -> AskResponse:
    before = [s for s in route.stops if s.role == "before"]
    target = next(s for s in route.stops if s.role == "target")
    if req.intent == "why_before":
        if not before:
            return AskResponse(answer=f"You can start {target.book.title} today; nothing on the path needs to come first.", engine="template")
        lines = [f"{s.book.title} first: {s.why.rstrip('.')}." for s in before]
        return AskResponse(answer=" ".join(lines), engine="template")
    if req.intent == "time_budget":
        weeks = max(1, req.weeks or 2)
        budget = weeks * 5.0  # ~5 reading hours a week
        picked, used = [], 0.0
        for s in before + [target]:
            if used + s.readiness.hours <= budget or s.role == "target":
                picked.append(s)
                used += s.readiness.hours
        skipped = [s for s in before if s not in picked]
        msg = f"In {weeks} week(s) at about 5 hours a week you can fit: " + ", ".join(s.book.title for s in picked) + f" (~{used:.0f} h)."
        if skipped:
            msg += " Skip for now: " + ", ".join(s.book.title for s in skipped) + "."
        return AskResponse(answer=msg, adjusted_stop_ids=[s.book.id for s in picked], engine="template")
    if req.intent == "large_print":
        return AskResponse(
            answer="The path shows regular print copies. Large-print and audiobook editions are not in this demo's data yet; ask the counter at any branch or check the NLB app for an audiobook of each stop.",
            engine="template",
        )
    return AskResponse(answer="Ask about why a book comes first, how long the path takes, or large-print options.", engine="template")


def answer(route: Route, req: AskRequest) -> AskResponse:
    """Model answer when AI is on and it replies, else the template (engine says which)."""
    if config.llm_enabled():
        q = {
            "why_before": "Why do the books before the target come first? Mention each by title.",
            "time_budget": f"The reader has {req.weeks or 2} weeks at about 5 hours a week. Which stops fit, in order, and what should they skip?",
            "large_print": "The reader is 65 and prefers large print or audio. What should they know about this line?",
            "free": req.question or "Summarise the line.",
        }[req.intent]
        brief = _route_brief(route)
        text = llm.ask(brief, q, req.lang) if req.lang else llm.ask(brief, q)
        if text:
            return AskResponse(answer=text, engine="llm")
    return _template(route, req)
