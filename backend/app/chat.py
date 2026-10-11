"""Guided chat: free text in, a few questions, then a line + directions.

The flow is a small state machine so it behaves the same with or without the
LLM. With OPENAI_API_KEY the free-text step is parsed by the model (title /
author / topic); without it we keyword-match the cached catalogue.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config, llm
from .availability import BRANCHES
from .engine import load_index, load_route, seeds

log = logging.getLogger("prereads.chat")

Step = Literal["start", "pick", "level", "branch", "done"]


class ChatState(BaseModel):
    step: Step = "start"
    book_id: Optional[str] = None
    candidates: list[dict] = Field(default_factory=list)
    level: Optional[int] = None
    branch: Optional[str] = None


class ChatOption(BaseModel):
    label: str
    value: str


class ChatTurn(BaseModel):
    text: str
    state: ChatState


class ChatReply(BaseModel):
    messages: list[str]
    options: list[ChatOption] = Field(default_factory=list)
    state: ChatState
    result: Optional[dict] = None   # {book_id, title, author, level, branch, start, start_status}


class Intent(BaseModel):
    kind: Literal["title", "author", "topic", "unclear"]
    value: str


# ------------------------------------------------------------------ catalogue
def _catalogue() -> list[dict]:
    """Cached targets with subjects, for matching."""
    idx = {e["id"]: e for e in load_index()}
    out = []
    for s in seeds():
        sid = s.get("isbn") or s.get("id")
        if sid in idx or load_route(sid):
            out.append({"id": sid, "title": s["title"], "author": s.get("author", ""), "subjects": s.get("subjects", []), "level": s.get("level", 3)})
    return out


def _tokens(s: str) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if len(t) > 2}


def match(text: str) -> list[dict]:
    q = _tokens(text)
    if not q:
        return []
    scored = []
    for b in _catalogue():
        title_t, author_t = _tokens(b["title"]), _tokens(b["author"])
        subj_t = _tokens(" ".join(b["subjects"]))
        score = 3 * len(q & title_t) + 2 * len(q & author_t) + len(q & subj_t)
        if score:
            scored.append((score, b))
    scored.sort(key=lambda x: -x[0])
    best = scored[0][0] if scored else 0
    return [b for sc, b in scored if sc >= max(1, best - 1)][:5]


def parse_intent(text: str) -> Intent:
    if config.llm_enabled():
        r = llm.structured(
            Intent,
            "Classify a library reader's message as a book title, an author name, or a topic they want to learn. Return the cleaned value.",
            text,
        )
        if r:
            return r
    return Intent(kind="topic", value=text)


# ----------------------------------------------------------------------- flow
LEVELS = [("New to this", "1"), ("Read a bit", "3"), ("Know it well", "4")]


def _ask_level(state: ChatState, lead: str) -> ChatReply:
    state.step = "level"
    return ChatReply(messages=[lead, "How familiar are you with this topic?"], options=[ChatOption(label=l, value=v) for l, v in LEVELS], state=state)


def _ask_branch(state: ChatState) -> ChatReply:
    state.step = "branch"
    opts = [ChatOption(label="Any library", value="")] + [ChatOption(label=n.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", ""), value=c) for c, n in BRANCHES.items()]
    return ChatReply(messages=["Which library will you go to? I'll check the shelf there."], options=opts, state=state)


def _finish(state: ChatState) -> ChatReply:
    state.step = "done"
    route = load_route(state.book_id or "")
    if route is None:
        return ChatReply(messages=["I couldn't build that reading path. Try searching for the title instead."], state=ChatState())
    target = next(s for s in route.stops if s.role == "target")
    level = state.level or 1
    before = [s for s in route.stops if s.role == "before" and s.readiness.level >= level]
    start = before[0] if before else target
    # shelf status for the start book at the chosen branch
    av = start.availability
    chosen = next((a for a in av if a.branch_code == state.branch), None) if state.branch else None
    if chosen and chosen.available > 0:
        status = f"available at {chosen.branch} ({chosen.call_number})"
    else:
        best = max((a for a in av if a.available > 0), key=lambda a: a.available, default=None)
        status = f"available at {best.branch} ({best.call_number})" if best else "all copies out — join the waiting list"
    hours = sum(s.readiness.hours for s in before)
    if before:
        lead = f"{len(before)} {'book' if len(before) == 1 else 'books'} before {target.book.title}, about {round(hours)} hours. Start with {start.book.title} — {status}."
    else:
        lead = f"You can start {target.book.title} today — {status}."
    result = {
        "book_id": route.target_id,
        "title": target.book.title,
        "author": target.book.author,
        "level": level,
        "branch": state.branch or "",
        "start_id": start.book.id,
        "start_title": start.book.title,
        "start_status": status,
    }
    return ChatReply(messages=[lead, "I've drawn the reading path and the directions to the first book."], state=state, result=result)


def step(turn: ChatTurn) -> ChatReply:
    state = turn.state
    text = (turn.text or "").strip()

    if state.step == "start" or (state.step == "pick" and not text.isdigit()):
        if not text:
            return ChatReply(messages=["What do you want to read or learn? A title, an author, or a topic like 'investing' all work."], state=ChatState())
        intent = parse_intent(text)
        hits = match(intent.value) or match(text)
        if not hits:
            return ChatReply(
                messages=[f"I couldn't find '{text}' in the catalogue yet. Try the exact title, or a broad topic like 'physics' or 'investing'."],
                state=ChatState(),
            )
        if len(hits) == 1:
            state.book_id = hits[0]["id"]
            return _ask_level(state, f"Got it: {hits[0]['title']} by {hits[0]['author']}.")
        state.step = "pick"
        state.candidates = hits
        return ChatReply(
            messages=["A few books match. Which one did you mean?"],
            options=[ChatOption(label=f"{h['title']} — {h['author']}", value=str(i)) for i, h in enumerate(hits)],
            state=state,
        )

    if state.step == "pick":
        i = int(text)
        if 0 <= i < len(state.candidates):
            state.book_id = state.candidates[i]["id"]
            return _ask_level(state, f"Great: {state.candidates[i]['title']}.")
        return ChatReply(messages=["Pick one of the options above."], options=[ChatOption(label=f"{h['title']} — {h['author']}", value=str(i)) for i, h in enumerate(state.candidates)], state=state)

    if state.step == "level":
        try:
            state.level = int(text)
        except ValueError:
            lower = text.lower()
            state.level = 4 if "well" in lower or "expert" in lower else 3 if "bit" in lower or "some" in lower else 1
        return _ask_branch(state)

    if state.step == "branch":
        state.branch = text if text in BRANCHES else None
        return _finish(state)

    return ChatReply(messages=["Type a title, author or topic to start again."], state=ChatState())


# --------------------------------------------------------------------- browse
def browse(by: str) -> list[dict]:
    cat = _catalogue()
    if by == "author":
        seen: dict[str, dict] = {}
        for b in cat:
            seen.setdefault(b["author"], {"label": b["author"], "count": 0, "ids": []})
            seen[b["author"]]["count"] += 1
            seen[b["author"]]["ids"].append(b["id"])
        return sorted(seen.values(), key=lambda e: e["label"].split(" ")[-1])
    groups: dict[str, dict] = {}
    for b in cat:
        label = (b["subjects"] or ["Other"])[0]
        groups.setdefault(label, {"label": label, "count": 0, "ids": []})
        groups[label]["count"] += 1
        groups[label]["ids"].append(b["id"])
    return sorted(groups.values(), key=lambda e: (-e["count"], e["label"]))


def books_for(ids: list[str]) -> list[dict]:
    cat = {b["id"]: b for b in _catalogue()}
    return [cat[i] for i in ids if i in cat]


def to_json(reply: ChatReply) -> str:
    return json.dumps(reply.model_dump())
