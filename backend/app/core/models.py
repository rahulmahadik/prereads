"""Pydantic domain models shared by every layer: Book, Readiness, Judgment, CandidateList,
Availability, Demand, Stop, Route, ScanResult and the ask request/response.

Layer: core. These are also the structured-output schemas sent to the model (ai.llm builds
the json_schema response_format from them), so a field change here is a prompt-contract
change: update the prompt that produces it.
"""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field


def slugify(title: str, author: str = "") -> str:
    """Stable id for a book with no ISBN: lower-case title + author, dashes, max 80 chars."""
    base = f"{title} {author}".lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")
    return base[:80]


class Book(BaseModel):
    id: str                                  # ISBN-13 when known, else "ol:<slug>"
    title: str
    author: str = ""
    isbn: Optional[str] = None
    brn: Optional[str] = None                # NLB bib record number when known
    year: Optional[int] = None
    pages: Optional[int] = None
    ddc: Optional[str] = None                # Dewey class (e.g. "153.4") from Open Library when known
    subjects: list[str] = Field(default_factory=list)
    summary: str = ""
    cover_url: Optional[str] = None
    reservations: int = 0                    # NLB activeReservationsCount when known
    audience: list[str] = Field(default_factory=list)   # e.g. ["Adult"], ["Children"]
    source: str = "seed"                     # seed | openlibrary | nlb
    field_sources: dict[str, str] = Field(default_factory=dict)  # field -> source that filled it (catalog.enrich)


class Readiness(BaseModel):
    level: int = Field(ge=1, le=5)           # 1 newcomer ... 5 specialist
    hours: float = Field(ge=0.5, le=80)      # typical adult reading time
    assumed_concepts: list[str] = Field(default_factory=list)
    style_tags: list[str] = Field(default_factory=list)
    one_line: str = ""                       # what you need to know going in


class Judgment(BaseModel):
    relation: Literal["prepares_for", "same_level", "follows", "unrelated"]
    confidence: float = Field(ge=0, le=1)
    reason: str                              # one sentence a librarian would say


class Availability(BaseModel):
    branch: str
    branch_code: str = ""
    call_number: str = ""
    available: int = 0
    total: int = 0
    demo: bool = False


class Demand(BaseModel):
    hot_branches: list[str] = Field(default_factory=list)
    hidden_gem: bool = False
    reservations: int = 0                    # people in the queue (NLB activeReservationsCount)
    demo: bool = False


class Stop(BaseModel):
    role: Literal["before", "target", "after"]
    order: int
    book: Book
    readiness: Readiness
    why: str                                 # why this stop is on the line
    confidence: float = 1.0
    availability: list[Availability] = Field(default_factory=list)
    demand: Demand = Field(default_factory=Demand)


class Route(BaseModel):
    target_id: str
    stops: list[Stop]
    generated_at: str
    engine: str                              # "llm" | "heuristic" | "seed"
    notes: list[str] = Field(default_factory=list)


class CandidateList(BaseModel):
    before: list[dict]                       # {title, author, why}
    after: list[dict]


class ScanResult(BaseModel):
    title: str
    author: str = ""
    isbn: Optional[str] = None
    confidence: float = 0.0


class AskRequest(BaseModel):
    target_id: str
    intent: Literal["why_before", "time_budget", "large_print", "free"]
    weeks: Optional[int] = None
    question: Optional[str] = None
    lang: Optional[str] = None          # reader's UI language (en/zh/ms/ta): AI-written text follows it


class AskResponse(BaseModel):
    answer: str
    adjusted_stop_ids: list[str] = Field(default_factory=list)
    engine: str
