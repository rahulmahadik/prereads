"""Reading-age estimate for a book. Mirrored by frontend/src/readingAge.ts: keep the two identical.

Catalogue signals win (audience, then juvenile / young adult subjects). Otherwise the
readiness level decides. Only a straight catalogue audience is marked "catalogue".
"""
from __future__ import annotations

import json
from typing import Optional

from pydantic import BaseModel, Field

from . import config
from .models import Book, Readiness

CHILD = ("Children 8–12", 8)
TEEN = ("Teen", 13)
ADULT = ("Adult", 18)


def _kind(texts: list[str]) -> Optional[str]:
    joined = " | ".join(t.lower() for t in texts)
    if "young adult" in joined or "teen" in joined:
        return "teen"
    if "juvenile" in joined or "child" in joined:
        return "child"
    if "adult" in joined:
        return "adult"
    return None


def _result(label: str, min_age: int, source: str) -> dict:
    return {"label": label, "min_age": min_age, "source": source}


def heuristic(audience: list[str], subjects: list[str], level: int, pages: Optional[int]) -> dict:
    aud = _kind(audience)
    if aud == "child":
        return _result(*CHILD, "catalogue")
    if aud == "teen":
        return _result(*TEEN, "catalogue")
    if aud == "adult":
        return _result(*ADULT, "catalogue")
    sub = _kind([s for s in subjects if "adult" not in s.lower() or "young adult" in s.lower()])
    if sub == "child":
        return _result(*CHILD, "estimated")
    if sub == "teen":
        return _result(*TEEN, "estimated")
    if level <= 2:
        return _result("Reading age 15+", 15, "estimated") if (pages or 0) >= 500 else _result("Reading age 12+", 12, "estimated")
    if level == 3:
        return _result("Reading age 15+", 15, "estimated")
    return _result(*ADULT, "estimated")


class _AgeReply(BaseModel):
    min_age: int = Field(ge=5, le=18)


def _cache_path(book_id: str):
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in book_id)
    return config.CACHE_DIR / "reading_age" / f"{safe}.json"


def _label_for(min_age: int) -> str:
    if min_age >= 18:
        return ADULT[0]
    if min_age <= 11:
        return CHILD[0]
    return f"Reading age {min_age}+"


def _llm_min_age(book: Book) -> Optional[int]:
    from . import llm
    r = llm.structured(
        _AgeReply,
        "You give the youngest age (5-18) at which a reader can comfortably read a book. Reply as JSON {\"min_age\": n}.",
        f"{book.title} by {book.author}. Subjects: {', '.join(book.subjects[:6])}. {book.summary[:300]}",
        kind="reading_age", temperature=0.2,
    )
    return r.min_age if r else None


def estimate(book: Book, readiness: Readiness, use_llm: bool = False) -> dict:
    base = heuristic(book.audience, book.subjects, readiness.level, book.pages)
    if base["source"] == "catalogue" or not use_llm or not config.llm_enabled():
        return base
    path = _cache_path(book.id)
    try:
        if path.exists():
            return json.loads(path.read_text())
    except (OSError, ValueError):
        pass
    try:
        age = _llm_min_age(book)
    except Exception:
        age = None
    if age is None:
        return base
    out = _result(_label_for(age), age, "estimated")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(out))
    except OSError:
        pass
    return out
