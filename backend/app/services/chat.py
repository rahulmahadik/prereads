"""Guided chat: free text in, a few questions, then a reading path + directions.

The flow is a small state machine (start -> pick -> level -> branch -> done) so it
behaves the same with or without the model. The free-text step is
retrieval-augmented over our own data:

  understand  rules first (too vague? an exact title or author?), then the model
  retrieve    nomic-embed-text over every catalogue-verified book on a cached path
              (discover._catalogue), keyword scoring as the fallback
  choose      the model picks the best 3 FROM the retrieved list; any id outside
              it is dropped (never an unverified book); top 3 by score without a model
  shelves     reader-facing status for each option (the source is shown in Settings)

Every reply carries `trace`: the steps that actually ran, with real counts and timings.

Layer: services. Served by api/routes_chat.py (/api/chat and /api/chat/stream);
browse()/books_for() also back /api/browse. Reuses services.discover's catalogue and
scoring, so both features agree.
"""
from __future__ import annotations

import asyncio
import concurrent.futures as cf
import contextvars
import json
import logging
import os
import queue
import re
import threading
import time
from contextlib import contextmanager
from difflib import SequenceMatcher
from typing import AsyncIterator, Callable, Iterator, Literal, Optional

from pydantic import BaseModel, Field

from ..core import config
from . import discover
from ..ai import embeddings, llm
from ..integrations.availability import BRANCHES
from ..integrations.catalog import title_matches
from .engine import load_index, load_route, seeds

log = logging.getLogger("prereads.chat")

Step = Literal["start", "pick", "level", "branch", "done"]


class ChatState(BaseModel):
    step: Step = "start"
    book_id: Optional[str] = None       # the cached reading path (its target id)
    focus_id: Optional[str] = None      # the book the reader picked: the target, or a stop on that path
    candidates: list[dict] = Field(default_factory=list, max_length=12)
    level: Optional[int] = None
    branch: Optional[str] = None
    # Conversation memory, round-tripped by the client with the rest of the state, so a
    # follow-up ("something easier", "the second one", "who wrote it?") has something to refer to.
    topic: Optional[str] = Field(None, max_length=200)   # the subject in play, as a standalone search ("investing")
    shown: list[dict] = Field(default_factory=list, max_length=12)    # the books last put in front of the reader, in order
    history: list[dict] = Field(default_factory=list, max_length=12)  # recent turns [{role, text}], oldest first


class ChatOption(BaseModel):
    label: str
    value: str
    hint: str = ""                      # one line under the label: why it fits, shelf status


class ChatTurn(BaseModel):
    text: str = Field(max_length=500)
    state: ChatState
    lang: Optional[str] = None          # reader's UI language: AI-written reasons follow it


class TraceStep(BaseModel):
    step: str
    detail: str = ""
    ms: int = 0


class ChatReply(BaseModel):
    messages: list[str]
    options: list[ChatOption] = Field(default_factory=list)
    state: ChatState
    result: Optional[dict] = None   # {book_id, title, author, level, branch, start_id, start_title, start_status}
    trace: list[TraceStep] = Field(default_factory=list)


class Intent(BaseModel):
    kind: Literal["title", "author", "topic", "unclear"]
    value: str


class Pick(BaseModel):
    id: str
    reason: str


# ------------------------------------------------------------------ trace
class Trace:
    """Records what actually ran: step name, a detail line with real counts, and elapsed ms."""

    def __init__(self) -> None:
        self.steps: list[TraceStep] = []

    @contextmanager
    def step(self, name: str) -> Iterator[TraceStep]:
        rec = TraceStep(step=name)
        t0 = time.perf_counter()
        _emit({"type": "start", "step": name})            # streamed live to the chat panel
        try:
            yield rec
        finally:
            rec.ms = round((time.perf_counter() - t0) * 1000)
            self.steps.append(rec)
            _emit({"type": "done", "step": rec.step, "detail": rec.detail, "ms": rec.ms})


# Set by the streaming endpoint: receives each step as it starts and finishes, so the
# progress the reader sees is the real work, not a timer.
_ON_STEP: "contextvars.ContextVar[Optional[Callable[[dict], None]]]" = contextvars.ContextVar("chat_on_step", default=None)


def _emit(event: dict) -> None:
    cb = _ON_STEP.get()
    if cb is not None:
        try:
            cb(event)
        except Exception:  # noqa: BLE001 - a closed stream must never break the reply
            pass


def _start_stream(turn: "ChatTurn") -> "queue.Queue[Optional[str]]":
    """Run the turn on its own thread; each real step event and then the reply land in the queue."""
    q: "queue.Queue[Optional[str]]" = queue.Queue()

    def run() -> None:
        _ON_STEP.set(lambda e: q.put(json.dumps(e, ensure_ascii=False)))
        try:
            reply = step(turn)
            q.put(json.dumps({"type": "reply", "reply": reply.model_dump()}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            q.put(json.dumps({"type": "error", "message": str(exc)[:200]}))
        finally:
            q.put(None)

    threading.Thread(target=run, daemon=True).start()
    return q


def stream(turn: "ChatTurn") -> Iterator[str]:
    """NDJSON stream: one line per real step event, then the final reply."""
    q = _start_stream(turn)
    while True:
        line = q.get()
        if line is None:
            return
        yield line + "\n"


async def astream(turn: "ChatTurn") -> AsyncIterator[str]:
    """stream() for the server: waits on the event loop, not on a worker thread, so a page full of
    open chats can't use up the threads every other request needs."""
    q = _start_stream(turn)
    while True:
        try:
            line = q.get_nowait()
        except queue.Empty:
            await asyncio.sleep(0.03)
            continue
        if line is None:
            return
        yield line + "\n"


def _model_name() -> str:
    return llm.resolve_model("chat") if config.AI_PROVIDER == "ollama" else config.OPENAI_MODEL


def _short_branch(name: str) -> str:
    return name.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "")


# ------------------------------------------------------------------ catalogue
def _catalogue() -> list[dict]:
    """Cached targets with subjects (browse groups, books_for)."""
    idx = {e["id"]: e for e in load_index()}
    out = []
    for s in seeds():
        sid = s.get("isbn") or s.get("id")
        if sid in idx or load_route(sid):
            out.append({"id": sid, "title": s["title"], "author": s.get("author", ""), "subjects": s.get("subjects", []), "level": s.get("level", 3)})
    return out


def _books() -> list[dict]:
    """Every catalogue-verified book on a cached reading path (targets and their stops)."""
    return discover._catalogue()


def _line_titles() -> dict[str, str]:
    return {(s.get("isbn") or s.get("id")): s["title"] for s in seeds()}


def _tokens(s: str) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if len(t) > 2}


def _norm(s: str) -> str:
    return " ".join(re.sub(r"[^a-z0-9 ]", " ", s.lower()).split())


# ------------------------------------------------------------------ understanding
_FILLER = set(
    """i im i'm me my mine we us a an the to for of and or in on at with by from about into
    some something anything any every all good great nice interesting fun cool best top new popular
    book books read reading reads reader title titles author authors topic topics stuff thing things
    recommend recommendation recommendations suggest suggestion suggestions idea ideas help hi hello hey
    hiya yo please pls thanks thank you can could would should will what which who where how why want
    wanna like love need needs looking look find show give get tell there here is are be do does it
    that this these those ok okay hmm um start library libraries today now just really maybe more
    lot lots whatever else so one ones learn know understand something's morning afternoon evening""".split()
)


def is_vague(text: str) -> bool:
    """No subject, title or name left once the filler words are gone ('books', 'hi', 'something good')."""
    words = re.sub(r"[^a-z0-9' ]", " ", text.lower()).split()
    return not [w for w in words if w not in _FILLER and len(w) > 1 and not w.isdigit()]


def _title_score(value: str, title: str) -> float:
    v, t = _norm(value), _norm(title)
    main = _norm(title.split(":")[0])
    if not v or not t:
        return 0.0
    if v in (t, main):
        return 1.0
    if title_matches(value, title) and title_matches(title.split(":")[0], value):
        return 0.9
    return max(SequenceMatcher(None, v, t).ratio(), SequenceMatcher(None, v, main).ratio())


def _content(text: str) -> set[str]:
    return {w for w in _tokens(text) if w not in _FILLER}


def _author_hits(value: str, cat: list[dict]) -> list[dict]:
    q = _content(value)
    if not q or len(q) > 4:
        return []
    return [e for e in cat if q <= _tokens(e["author"])]


def _named(text: str, cat: list[dict]) -> Optional[Intent]:
    """Rules before the model: an exact (or near-exact) title, or an author we hold."""
    best = max(((_title_score(text, e["title"]), e) for e in cat), key=lambda x: x[0], default=(0.0, None))
    if best[1] is not None and best[0] >= 0.88:
        return Intent(kind="title", value=best[1]["title"])
    if _author_hits(text, cat):
        return Intent(kind="author", value=text.strip())
    return None


def rules(text: str, cat: list[dict]) -> Optional[tuple[Intent, str]]:
    """What code can decide without a model: too vague to search, or an exact title / author we hold."""
    if is_vague(text):
        return Intent(kind="unclear", value=text), "too general to search · asked a follow-up (rule)"
    named = _named(text, cat)
    if named:
        return named, f"{named.kind}: {named.value} · matched the catalogue directly"
    return None


def heuristic_intent(text: str) -> Intent:
    """Keyword topics when no model reads the request."""
    return Intent(kind="topic", value=" ".join(discover.heuristic_need(text).topics[:4]) or text.strip())


# ------------------------------------------------------------------ retrieval
def retrieve(query: str, cat: list[dict], k: int = 8, cats: frozenset = frozenset()) -> tuple[list[tuple[dict, float, str]], str]:
    """Top k (entry, fit, why) for a topic, best first, and the method used.
    Semantic search (centred cosine, nomic-embed-text) blended with keyword scoring;
    keywords alone when the embedding model is down."""
    need = discover.heuristic_need(query)
    if not need.topics:
        need.topics = sorted(_content(query)) or [query]
    ranked = embeddings.rank(query, [(e["id"], discover.entry_text(e)) for e in cat], top_k=len(cat))
    sims = dict(ranked) if ranked is not None else {}
    method = "semantic search" if ranked is not None else "keyword search"
    words = _content(query)
    scored = []
    for e in cat:
        fit, why = discover.score(e, need, {}, None, discover.semantic_topic(sims.get(e["id"], 0.0)))
        if e["category"] in cats:                      # a subject the reader tapped
            fit = max(fit, 0.6) + 0.2
        if fit > 0:
            # a plain word of the request in the title, category or subjects beats a synonym match
            fit += 0.04 * len(words & (_tokens(e["title"]) | _tokens(e["category"]) | _tokens(" ".join(e["subjects"]))))
            scored.append((e, round(fit, 3), why))
    # a target has its whole reading path cached, so it edges ahead on a tie
    scored.sort(key=lambda x: (-(x[1] + (0.03 if x[0]["is_target"] else 0.0)), x[0]["level"]))
    return scored[:k], method


# ------------------------------------------------------------------ the model (one call)
class Understood(BaseModel):
    kind: Literal["title", "author", "topic", "unclear"]
    value: str
    picks: list[Pick]


ASK_SYSTEM = (
    "You are PreReads, a public-library readers' advisor. REQUEST is the reader's message. CANDIDATES were "
    "retrieved from our library catalogue for it. CONVERSATION, when present, is the chat so far, oldest first: "
    "read REQUEST in its light, so a follow-up continues the earlier subject unless it names a new one. "
    "1) kind: title = they named a specific book; author = they "
    "named a writer; topic = a subject, question or need; unclear = a greeting or no subject at all. value: the "
    "book title, the author's name, or the subject in 1-4 plain words (e.g. 'investing', not 'understand investing'), "
    "standalone even for a follow-up (e.g. 'the brain, for children'). "
    "2) picks: the 3 CANDIDATES that best answer the request, best first; for a beginner or a child prefer a gentle start. "
    "reason: one plain, warm sentence to the reader, at most 14 words. Use only ids from CANDIDATES. Never invent a book."
)

_LANG: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("chat_lang", default=None)
MODEL_BUDGET = float(os.getenv("CHAT_MODEL_BUDGET", "25"))   # seconds; past this the chat answers without the model
_pool = cf.ThreadPoolExecutor(max_workers=4, thread_name_prefix="chat-llm")   # Ollama runs 4 in parallel


def ask_model(request: str, hits: list[tuple[dict, float, str]], history: Optional[list[dict]] = None) -> tuple[Optional[Understood], str]:
    """One model call: what the reader means, and the best 3 of the retrieved books. (None, why) on failure."""
    payload: dict = {"REQUEST": request}
    if history:
        payload["CONVERSATION"] = [f"{h['role']}: {h['text']}" for h in history[-4:]]
    payload["CANDIDATES"] = [{
        "id": e["id"], "title": e["title"], "author": e["author"], "level": e["level"], "hours": e["hours"],
        "about": [x for x in e["subjects"] + e["concepts"] if len(x.split()) <= 4][:6],
    } for e, _, _ in hits]
    user = json.dumps(payload, ensure_ascii=False)
    if not llm.reserve():               # other readers have the model: answer from the search now
        return None, "AI busy with other readers"
    fut = _pool.submit(llm.structured, Understood, llm.with_lang(ASK_SYSTEM, _LANG.get()), user, kind="chat", temperature=0.2)
    fut.add_done_callback(llm.release)
    try:
        r = fut.result(timeout=MODEL_BUDGET)
    except cf.TimeoutError:
        return None, f"{_model_name()} gave no answer in {round(MODEL_BUDGET)} s"
    except Exception as exc:  # noqa: BLE001
        log.warning("chat model call failed: %s", exc)
        r = None
    if r is None or not r.value.strip():
        return None, f"{_model_name()} reply unusable"
    return r, ""


def validate_picks(picks: list[Pick], hits: list[tuple[dict, float, str]], k: int = 3) -> tuple[list[tuple[dict, str]], int]:
    """Keep only ids that were retrieved (catalogue-verified); returns (picks, dropped count)."""
    by_id = {e["id"]: (e, why) for e, _, why in hits}
    out: list[tuple[dict, str]] = []
    dropped = 0
    for p in picks:
        if p.id not in by_id:          # never a book outside the verified, retrieved list
            dropped += 1
            continue
        if any(e["id"] == p.id for e, _ in out):
            continue
        reason = p.reason.strip().rstrip(".") + "." if p.reason.strip() else _reason(*by_id[p.id])
        out.append((by_id[p.id][0], reason))
        if len(out) == k:
            break
    return out, dropped


def top_by_score(hits: list[tuple[dict, float, str]], k: int = 3) -> list[tuple[dict, str]]:
    return [(e, _reason(e, why)) for e, _, why in hits[:k]]


def _reason(e: dict, why: str = "") -> str:
    text = (why or e.get("one_line") or "A strong match for what you asked.").strip()
    first = re.split(r"(?<=[.!?])\s", text)[0]
    return first if len(first) <= 110 else first[:107].rstrip() + "…"


# ------------------------------------------------------------------ options
GROUPS = [
    ("Psychology & decisions", "psychology, decisions, habits and how we think", {"Psychology", "Habits", "Probability"}),
    ("Investing & money", "investing, money and economics", {"Investing", "Economics"}),
    ("Science for everyone", "popular science: the universe, evolution, sleep and health", {"Cosmology", "Evolution", "Sleep", "Cancer"}),
    ("Philosophy", "philosophy, stoicism and how to think clearly", {"Stoicism", "Philosophy of science", "Logic"}),
    ("Computers & AI", "computers, algorithms, software and AI", {"Machine learning", "Algorithms", "Software architecture", "Databases", "Cryptography"}),
    ("History", "history of the world and of Singapore", {"World history", "Singapore"}),
]


def _popular(cat: list[dict]) -> list[dict]:
    """Same demand score as /api/popular: hot branches, queue, copies out."""
    rows = []
    for e in cat:
        if not e["is_target"]:
            continue
        r = load_route(e["line_id"])
        if not r:
            continue
        t = next(x for x in r.stops if x.role == "target")
        total = sum(a.total for a in t.availability) or 1
        out = sum(a.total - a.available for a in t.availability)
        rows.append((3 * len(t.demand.hot_branches) + 2 * t.demand.reservations + 2 * (out / total), e, t.demand.demo))
    rows.sort(key=lambda x: (-x[0], x[1]["title"]))
    return [{**e, "demo": demo} for _, e, demo in rows]


def starter_options(cat: list[dict], n_groups: int = 3) -> tuple[list[ChatOption], str]:
    counts = [(label, query, sum(1 for e in cat if e["category"] in cats)) for label, query, cats in GROUPS]
    counts = sorted([c for c in counts if c[2] >= 2], key=lambda c: -c[2])[:n_groups]
    opts = [ChatOption(label=label, value=f"topic:{label}", hint=f"{n} books") for label, _, n in counts]
    pop = _popular(cat)[:1]
    for p in pop:
        opts.append(ChatOption(label=p["title"], value=f"book:{p['id']}", hint="Readers' pick"))
    extra = " and a readers' pick" if pop else ""
    detail = f"{len(counts)} subjects{extra} from {len(cat)} books"
    return opts, detail


def _status(e: dict) -> str:
    return discover.status_for(e, None)[0]


def _book_option(i: int, e: dict, reason: str = "") -> ChatOption:
    status = _status(e)
    hint = " · ".join(x for x in (reason, status) if x)
    return ChatOption(label=f"{e['title'].split(':')[0].strip()} — {e['author']}", value=str(i), hint=hint)


def _cand(e: dict) -> dict:
    return {"id": e["id"], "line_id": e["line_id"], "title": e["title"], "author": e["author"], "is_target": e["is_target"],
            "level": e.get("level"), "category": e.get("category", "")}


def _shelf_step(tr: Trace, entries: list[dict]) -> None:
    with tr.step("Checking shelves") as s:
        on = sum(_status(e).startswith("Available") for e in entries)
        s.detail = f"{on} of {len(entries)} on a shelf now, across {len(BRANCHES)} libraries"


# ----------------------------------------------------------------------- flow
LEVELS = [("New to this", "1"), ("Read a bit", "3"), ("Know it well", "4")]


LEVEL_Q = "How familiar are you with this topic?"
BRANCH_Q = "Which library will you go to? I'll check the shelf there."


def _level_options() -> list[ChatOption]:
    return [ChatOption(label=l, value=v) for l, v in LEVELS]


def _branch_options() -> list[ChatOption]:
    return [ChatOption(label="Any library", value="")] + [ChatOption(label=_short_branch(n), value=c) for c, n in BRANCHES.items()]


def _ask_level(state: ChatState, lead: str, trace: Optional[list[TraceStep]] = None) -> ChatReply:
    state.step = "level"
    state.candidates = []
    return ChatReply(messages=[lead, LEVEL_Q], options=_level_options(), state=state, trace=trace or [])


def _ask_branch(state: ChatState) -> ChatReply:
    state.step = "branch"
    return ChatReply(messages=[BRANCH_Q], options=_branch_options(), state=state)


def _fresh(state: ChatState) -> ChatState:
    """A new request: the flow starts over, the conversation memory carries on."""
    return ChatState(topic=state.topic, shown=state.shown, history=state.history)


def _choose_book(state: ChatState, c: dict, trace: Optional[list[TraceStep]] = None) -> ChatReply:
    state.book_id = c.get("line_id") or c["id"]
    state.focus_id = c["id"]
    state.topic = c.get("category") or state.topic
    if not any(x["id"] == c["id"] for x in state.shown):
        state.shown = [c]
    lead = f"Got it: {c['title']} by {c['author']}."
    if not c.get("is_target"):
        line = _line_titles().get(c["line_id"])
        if line:
            lead += f" It's on the reading path to {line}."
    return _ask_level(state, lead, trace)


def _clarify(tr: Trace, cat: list[dict], lead: str, state: Optional[ChatState] = None) -> ChatReply:
    with tr.step("Looking at what we have") as s:
        opts, s.detail = starter_options(cat)
    return ChatReply(
        messages=[lead, "These subjects have the most books."],
        options=opts, state=_fresh(state) if state else ChatState(), trace=tr.steps,
    )


def _offer(tr: Trace, state: ChatState, picks: list[tuple[dict, str]], messages: list[str]) -> ChatReply:
    _shelf_step(tr, [e for e, _ in picks])
    state.step = "pick"
    state.candidates = [_cand(e) for e, _ in picks]
    state.shown = list(state.candidates)
    return ChatReply(messages=messages, options=[_book_option(i, e, r) for i, (e, r) in enumerate(picks)], state=state, trace=tr.steps)


def _picked(tr: Trace, hits: list[tuple[dict, float, str]], res: Optional[Understood], why_not: str) -> list[tuple[dict, str]]:
    """Trace step for the choice: the model's picks (validated against the retrieved list) or the top 3 by score."""
    with tr.step("Choosing the best 3") as s:
        if res is None:
            s.detail = (why_not + " · " if why_not else "") + "top 3 by fit score"
            return top_by_score(hits)
        picks, dropped = validate_picks(res.picks, hits)
        note = f" · {dropped} unknown {'id' if dropped == 1 else 'ids'} dropped" if dropped else ""
        if not picks:
            s.detail = f"no usable picks{note} · top 3 by fit score"
            return top_by_score(hits)
        s.detail = f"{_model_name()} picked {len(picks)} of {len(hits)} in the same call{note}"
        return picks


def _ask(tr: Trace, request: str, hits: list[tuple[dict, float, str]], step_name: str, history: Optional[list[dict]] = None) -> tuple[Optional[Understood], str]:
    if not config.llm_enabled():
        return None, "no model"
    with tr.step(step_name) as s:
        res, why_not = ask_model(request, hits, history)
        s.detail = (f"{res.kind}: {res.value.strip()} · model {_model_name()}" if config.AI_PROVIDER == "ollama" else f"{res.kind}: {res.value.strip()} · {_model_name()}") if res else why_not
    return res, why_not


def _search(tr: Trace, query: str, cat: list[dict], cats: frozenset = frozenset(), k: int = 8) -> list[tuple[dict, float, str]]:
    with tr.step("Searching the catalogue") as s:
        hits, method = retrieve(query, cat, k=k, cats=cats)
        s.detail = f"{len(hits)} {'match' if len(hits) == 1 else 'matches'} from {len(cat)} books ({method})"
    return hits


def _recommend(tr: Trace, state: ChatState, cat: list[dict], hits: list[tuple[dict, float, str]], picks: list[tuple[dict, str]], label: str, request: str) -> ChatReply:
    if not hits or not picks:
        return _clarify(tr, cat, f"{_say('not_found', q=request.strip())} {_say('help')}", state)
    state.topic = label
    about = " ".join(w for w in label.split() if w.lower() not in _FILLER) or label
    about = about if len(about) <= 40 else "that"
    weak = hits[0][1] < 0.62
    if about == "that":
        lead = "I don't have much on that, but these come closest." if weak else f"Here are {len(picks)} good places to start."
    else:
        lead = f"I don't have much on {about}, but these come closest." if weak else f"Here are {len(picks)} good places to start on {about}."
    return _offer(tr, state, picks, [lead])


def _saved_path_for(title: str) -> Optional[dict]:
    """A reading path built earlier for another reader (not in the curated list) whose title matches,
    as a chat candidate; None when there is none."""
    best = max(((_title_score(title, e.get("title", "")), e) for e in load_index()), key=lambda x: x[0], default=(0.0, None))
    if best[1] is None or best[0] < 0.88:
        return None
    route = load_route(best[1]["id"])
    target = next((x for x in route.stops if x.role == "target"), None) if route else None
    if target is None:
        return None
    return {"id": route.target_id, "line_id": route.target_id, "title": target.book.title, "author": target.book.author,
            "is_target": True, "level": target.readiness.level, "category": ""}


def _asked(intent: Intent, text: str) -> str:
    """What to quote back when nothing is found: the reader's own words unless the model's reading shares them."""
    return intent.value if _content(intent.value) & _content(text) else text


def _find_named(tr: Trace, state: ChatState, cat: list[dict], intent: Intent, text: str, nearest: Optional[list[tuple[dict, str]]] = None) -> ChatReply:
    with tr.step("Searching the catalogue") as s:
        if intent.kind == "author":
            hits = sorted(_author_hits(intent.value, cat) or _author_hits(text, cat), key=lambda e: (not e["is_target"], e["level"]))
            how = "author match"
        else:
            scored = sorted(((max(_title_score(intent.value, e["title"]), _title_score(text, e["title"])), e) for e in cat), key=lambda x: -x[0])
            strong = [e for sc, e in scored if sc >= 0.88]
            hits = strong[:1] if strong else [e for sc, e in scored if sc >= 0.62 or title_matches(intent.value, e["title"])][:4]
            how = "fuzzy title match"
        s.detail = f"{len(hits)} {'match' if len(hits) == 1 else 'matches'} from {len(cat)} books ({how})"
    if len(hits) == 1:
        return _choose_book(state, _cand(hits[0]), tr.steps)
    if hits:
        picks = [(e, "") for e in hits[:5]]
        who = hits[0]["author"].split(",")[0].strip()
        state.topic = hits[0]["category"]
        return _offer(tr, state, picks, [f"I have {len(hits)} books by {who}. Which one?" if intent.kind == "author" else "A few books match. Which one did you mean?"])
    # not in the curated list: a path built earlier for another reader?
    saved = _saved_path_for(intent.value) or _saved_path_for(text)
    if saved is not None:
        return _choose_book(state, saved, tr.steps)
    # not held: offer the nearest books we do hold, by meaning
    if not nearest:
        with tr.step("Finding the closest books") as s:
            near, method = retrieve(f"{intent.value} {text}", cat, k=3)
            s.detail = f"{len(near)} nearest from {len(cat)} books ({method})"
        nearest = top_by_score(near)
    if not nearest:
        return _clarify(tr, cat, f"{_say('not_found', q=_asked(intent, text))} {_say('help')}", state)
    state.topic = intent.value
    return _offer(tr, state, nearest, [_say("not_found", q=_asked(intent, text)), _say("closest")])


# ------------------------------------------------------------------ not found, in the reader's language
CHAT_TEXT = {
    "not_found": {
        "en": "I couldn't find '{q}'. It may not be in Singapore's public library (NLB) collection, or PreReads doesn't have it yet: PreReads only shows books it can check in a library catalogue.",
        "zh": "没有找到“{q}”。这本书可能不在新加坡公共图书馆（NLB）的馆藏中，或者 PreReads 还没有收录：PreReads 只显示能在图书馆目录中核实的书。",
        "ms": "Saya tidak menjumpai \"{q}\". Buku ini mungkin tiada dalam koleksi perpustakaan awam Singapura (NLB), atau PreReads belum memilikinya: PreReads hanya menunjukkan buku yang dapat disemak dalam katalog perpustakaan.",
        "ta": "\"{q}\" கிடைக்கவில்லை. இது சிங்கப்பூர் பொது நூலகத் (NLB) தொகுப்பில் இல்லாமல் இருக்கலாம், அல்லது PreReads-இல் இன்னும் சேர்க்கப்படவில்லை: நூலகப் பட்டியலில் சரிபார்க்கக்கூடிய நூல்களை மட்டுமே PreReads காட்டும்.",
    },
    "help": {"en": "Here's what I can help with.", "zh": "这些是我能帮忙的主题：", "ms": "Ini perkara yang boleh saya bantu:", "ta": "நான் உதவக்கூடியவை இவை:"},
    "closest": {"en": "These are the closest books PreReads has:", "zh": "这些是 PreReads 里最接近的书：", "ms": "Ini buku paling hampir yang ada dalam PreReads:", "ta": "PreReads-இல் உள்ள மிக நெருக்கமான நூல்கள் இவை:"},
    "unreadable": {
        "en": "I couldn't read that one right now. Try writing it in English, or pick a subject below.",
        "zh": "暂时无法理解这条消息。请试试用英文输入，或在下面选一个主题。",
        "ms": "Saya tidak dapat membaca mesej itu sekarang. Cuba tulis dalam bahasa Inggeris, atau pilih subjek di bawah.",
        "ta": "இந்தச் செய்தியை இப்போது புரிந்துகொள்ள முடியவில்லை. ஆங்கிலத்தில் எழுதிப் பாருங்கள், அல்லது கீழே ஒரு தலைப்பைத் தேர்ந்தெடுங்கள்.",
    },
}


def _say(key: str, **kw) -> str:
    """A fixed chat sentence in the reader's UI language (English when it's another one)."""
    lang = (_LANG.get() or "en").strip().lower()[:2]
    table = CHAT_TEXT[key]
    return table.get(lang, table["en"]).format(**kw)


# ------------------------------------------------------------------ follow-ups
# Decided in code from the conversation memory (state.topic / shown / focus_id): which book
# a message points at, what it asks about that book, and whether it nudges the last list.
_ORD = "first|1st|second|2nd|third|3rd|fourth|4th|fifth|5th|last"
_ORDINALS = {"first": 0, "1st": 0, "second": 1, "2nd": 1, "third": 2, "3rd": 2, "fourth": 3, "4th": 3, "fifth": 4, "5th": 4, "last": -1}
_ORDINAL_RE = re.compile(rf"\bthe ({_ORD})\b|\b({_ORD}) (?:one|book|option|pick|title)\b|^\s*({_ORD})\b|(?:#|\bnumber |\bno\.? ?|\boption )([1-5])\b")
_PRONOUN_RE = re.compile(r"\b(it|its|that|this|that one|this one|that book|this book|the book)\b")
_PICK_RE = re.compile(rf"^\s*(i'?ll take |let'?s do |go with |pick |choose )?(the ({_ORD})( one| book)?|({_ORD})( one| book)?|that one|this one|that book|this book)( please)?\s*[.!]?\s*$")
_QUESTIONS = [
    ("author", re.compile(r"\bwho (wrote|writes|is the author|is it by)\b|\bauthor\b|\bwritten by\b|\bwho'?s it by\b")),
    ("where", re.compile(r"\bwhere\b|\bavailab|\bon (the )?shelf\b|\bin stock\b|\bcop(y|ies)\b|\bborrow\b|\bwhich librar")),
    ("before", re.compile(r"\bbefore\b|\bprereq|\bprepare\b|\bget ready\b|\breading path\b|\bread first\b|\bstart with\b|\bready for\b")),
    ("level", re.compile(r"\bhow (hard|difficult|easy|long|advanced|technical)\b|\blevel\b|\bhow many (hours|pages)\b|\bdifficult")),
    ("about", re.compile(r"\babout\b|\bmore (on|info|details)\b|\btell me\b|\bsummar|\bdescribe\b|\bwhat('?s| is) (it|that|this)\b|\bany good\b|\bworth\b")),
]
_MODIFIERS = [
    ("easier", re.compile(r"\b(easier|simpler|gentler|lighter|shorter|less (technical|advanced|difficult)|more basic|basics?|beginners?|introductory|intro)\b")),
    ("harder", re.compile(r"\b(harder|more advanced|advanced|deeper|more technical|in.depth|challenging|longer)\b")),
    ("more", re.compile(r"\b(more like|similar|others?|another|anything else|something else|more books|more options|different|alternatives?)\b|^\s*(show\s+)?(me\s+)?more\b")),
]
_FOLLOW_WORDS = set(
    """easier simpler gentler lighter shorter harder advanced deeper technical basic basics beginner beginners
    introductory intro challenging longer depth similar other others another else different alternative alternatives
    option options less than ones first 1st second 2nd third 3rd fourth 4th fifth 5th last take choose pick""".split()
)
_ASK_WORDS = set(
    """wrote writes written writer author available availability shelf shelves stock copy copies borrow long hard
    difficult easy level hours pages summary summarise summarize describe plot worth before prereq prerequisite
    prerequisites prepare ready path""".split()
)
_AUDIENCE = set("""kid kids child children childrens teen teens teenager teenagers young younger student students family son daughter""".split())
_BRANCH_WORDS = {w for n in BRANCHES.values() for w in _tokens(_short_branch(n))}


def _leftover(text: str) -> set[str]:
    """Words that would name a new subject, once filler, follow-up, question, branch and audience words are gone."""
    return {w for w in _content(text) if w not in _FOLLOW_WORDS | _ASK_WORDS | _AUDIENCE | _BRANCH_WORDS}


def _edition_key(title: str) -> str:
    """'Python Crash Course, 2nd Edition' and 'Python crash course' -> the same key."""
    main = re.sub(r",?\s*\(?\b(\d+(st|nd|rd|th)|second|third|fourth|fifth|new|revised|updated)\b.*\bedition\b.*$", "", title.split(":")[0], flags=re.I)
    return _norm(main)


def _topic_label(topic: str) -> str:
    """'Python (Computer program language)' -> 'Python'; common nouns lower-cased for a sentence."""
    t = re.sub(r"\s*\(.*?\)", "", topic).strip()
    return t if t.split(" ")[0] in ("Python", "Singapore") or t.isupper() else t[:1].lower() + t[1:]


def _branch_in(text: str) -> Optional[str]:
    """A branch code from the reader's words ('Woodlands', 'at tampines', or the code itself)."""
    if text in BRANCHES:
        return text
    low = text.lower()
    return next((c for c, n in BRANCHES.items() if _short_branch(n).lower() in low), None)


def _level_in(text: str) -> Optional[int]:
    low = text.lower().strip()
    if low.isdigit():
        return int(low)
    if re.search(r"\b(new|beginner|never|none|not at all|no idea|nothing)\b", low):
        return 1
    if re.search(r"\b(well|expert|advanced|a lot|lots)\b", low):
        return 4
    if re.search(r"\b(bit|some|little|a few)\b", low):
        return 3
    return None


def _ref(text: str, state: ChatState, cat: list[dict]) -> tuple[Optional[dict], bool]:
    """The book a follow-up points at: 'the second one', a title on screen, or 'it' / 'that one'.
    Returns (entry, ambiguous): ambiguous when 'it' could be any of several books on screen."""
    if not state.shown and not state.focus_id:
        return None, False
    by_id = {e["id"]: e for e in cat}
    low = text.lower()
    m = _ORDINAL_RE.search(low)
    if m and state.shown:
        w = m.group(1) or m.group(2) or m.group(3) or m.group(4)
        i = int(w) - 1 if w.isdigit() else _ORDINALS[w]
        if -len(state.shown) <= i < len(state.shown):
            return by_id.get(state.shown[i]["id"]), False
    words = _content(text)
    for c in state.shown:
        main = _content(c["title"].split(":")[0])
        if main and main <= words:
            return by_id.get(c["id"]), False
    # 'it' / 'that' only when the rest of the message names no new subject ("books that explain tax" is a new request)
    if _PRONOUN_RE.search(low) and not _leftover(text):
        fid = state.focus_id or (state.shown[0]["id"] if len(state.shown) == 1 else None)
        if fid:
            return by_id.get(fid), False
        return None, bool(state.shown)
    return None, False


def _pending(state: ChatState) -> tuple[list[str], list[ChatOption]]:
    """The question the flow is waiting on, so a side question doesn't lose it."""
    if state.step == "level":
        return [LEVEL_Q], _level_options()
    if state.step == "branch":
        return [BRANCH_Q], _branch_options()
    return [], []


def _answer(e: dict, q: str, text: str) -> list[str]:
    """A plain answer about one catalogue book, from our own data."""
    title = e["title"].split(":")[0].strip()
    if q == "author":
        return [f"{title} is by {e['author']}."]
    if q == "level":
        out = [f"{title} is level {e['level']} of 5, about {round(e['hours'])} hours of reading."]
        if e["concepts"]:
            out.append("It helps to know: " + ", ".join(e["concepts"][:4]) + ".")
        return out
    if q == "where":
        av = e["availability"]
        code = _branch_in(text)
        here = next((a for a in av if a.branch_code == code), None) if code else None
        in_stock = [a for a in av if a.available > 0]
        if here is not None and here.available > 0:
            return [f"Yes, {title} is on the shelf at {_short_branch(here.branch)} ({here.call_number})."]
        names = ", ".join(f"{_short_branch(a.branch)} ({a.call_number})" for a in in_stock[:3])
        if here is not None or code:
            where = _short_branch(BRANCHES.get(code or "", ""))
            return [f"{title} isn't on the shelf at {where} right now." + (f" You'll find it at {names}." if names else " All copies are out; you can join the waiting list.")]
        return [f"{title} is on the shelf at {names}." if names else f"All copies of {title} are out right now; you can join the waiting list."]
    about = e.get("blurb") or e.get("one_line") or ""
    out = [f"{title}, by {e['author']}." + (f" {about}" if about else "")]
    out.append(f"Level {e['level']} of 5, about {round(e['hours'])} hours of reading.")
    return out


def _relative(tr: Trace, state: ChatState, cat: list[dict], mod: str, base: Optional[dict] = None) -> ChatReply:
    """'Something easier' / 'more advanced' / 'more like this' / 'for kids': the last subject again,
    measured against the books already shown."""
    by_id = {e["id"]: e for e in cat}
    topic = state.topic or (base or by_id.get((state.shown or [{}])[0].get("id", ""), {})).get("category", "")
    seen = {c["id"] for c in state.shown}
    levels = [base["level"]] if base else [by_id[c["id"]]["level"] for c in state.shown if c["id"] in by_id]
    with tr.step("Using the conversation") as s:
        s.detail = f"{mod} · topic: {topic or 'none'} · {len(seen)} {'book' if len(seen) == 1 else 'books'} already shown"
    fresh = _fresh(state)
    if not topic:
        return _clarify(tr, cat, "Tell me a subject and I'll find books on it.", state)
    hits = _search(tr, topic, cat, k=24)
    # never another edition of a book already shown ("Python Crash Course, 2nd Edition")
    seen_titles = {_edition_key(c["title"]) for c in state.shown}
    pool = [h for h in hits if h[0]["id"] not in seen and _edition_key(h[0]["title"]) not in seen_titles]
    if mod == "easier":
        keep = sorted((h for h in pool if not levels or h[0]["level"] < min(levels)), key=lambda h: h[0]["level"])
    elif mod == "harder":
        keep = sorted((h for h in pool if not levels or h[0]["level"] > max(levels)), key=lambda h: h[0]["level"])
    elif mod == "gentle":
        keep = sorted(hits, key=lambda h: h[0]["level"])
    else:
        keep = pool
    about = _topic_label(topic)
    picks = top_by_score(keep)
    if picks:
        lead = {
            "easier": f"Here are {len(picks)} easier books on {about}.",
            "harder": f"Here are {len(picks)} more advanced books on {about}.",
            "gentle": f"PreReads is for adult readers, but these are the gentlest books I have on {about}.",
        }.get(mod, f"Here are {len(picks)} more on {about}.")
        return _offer(tr, fresh, picks, [lead])
    if pool:
        word = "easiest" if mod == "easier" else "most advanced"
        nearest = sorted(pool, key=lambda h: h[0]["level"] if mod == "easier" else -h[0]["level"])
        return _offer(tr, fresh, top_by_score(nearest), [f"Those are already the {word} books I have on {about}. These are the closest others."])
    return _clarify(tr, cat, f"That's everything I have on {about}. Here's what else I can help with.", state)


def _followup(state: ChatState, text: str) -> Optional[ChatReply]:
    """A message that refers back to the conversation, answered from memory; None when it's a new request."""
    if not (state.shown or state.focus_id or state.topic) or not text or text.isdigit() or text in BRANCHES or text.startswith(("book:", "topic:")):
        return None
    cat = _books()
    e, ambiguous = _ref(text, state, cat)
    low = text.lower()
    q = next((k for k, rx in _QUESTIONS if rx.search(low)), None)
    mod = next((k for k, rx in _MODIFIERS if rx.search(low)), None)
    if mod is None and _content(text) & _AUDIENCE:
        mod = "gentle"
    mid_flow = state.step in ("level", "branch")
    tr = Trace()
    if e is not None and q and not (mod and q == "about"):
        with tr.step("Using the conversation") as s:
            s.detail = f"{q} · {e['title']}"
        if q == "before":
            if mid_flow and e["id"] == state.focus_id:
                ask, opts = _pending(state)
                title = e["title"].split(":")[0].strip()
                return ChatReply(messages=[f"I'll show you what to read before {title}. One quick question first."] + ask, options=opts, state=state, trace=tr.steps)
            return _choose_book(_fresh(state), _cand(e), tr.steps)
        if not mid_flow:
            state.focus_id = e["id"]
        ask, opts = _pending(state)
        if not mid_flow:
            opts = [ChatOption(label="Plan my reading path", value=f"book:{e['id']}"),
                    ChatOption(label="Something easier", value="something easier"),
                    ChatOption(label="More like this", value="more like this")]
        return ChatReply(messages=_answer(e, q, text) + ask, options=opts, state=state, trace=tr.steps)
    if mod and not _leftover(text):
        return _relative(tr, state, cat, mod, e)
    if e is not None and _PICK_RE.match(low):
        with tr.step("Using the conversation") as s:
            s.detail = f"you picked {e['title']}"
        return _choose_book(_fresh(state), _cand(e), tr.steps)
    if ambiguous and (q or _PICK_RE.match(low)) and not mid_flow:
        state.step = "pick"
        state.candidates = list(state.shown)
        opts = [ChatOption(label=f"{c['title'].split(':')[0].strip()} — {c['author']}", value=str(i)) for i, c in enumerate(state.shown)]
        by_id = {x["id"]: x for x in cat}
        books = [by_id[c["id"]] for c in state.shown if c["id"] in by_id]
        if q in ("author", "level", "where") and books:
            # a short fact: answer it for every book on screen rather than asking which one
            with tr.step("Using the conversation") as s:
                s.detail = f"{q} · all {len(books)} books shown"
            return ChatReply(messages=[_answer(b, q, text)[0] for b in books], options=opts, state=state, trace=tr.steps)
        return ChatReply(messages=["Which book do you mean?"], options=opts, state=state)
    return None


def _start(state: ChatState, text: str) -> ChatReply:
    """A new request. `state` carries the conversation memory; the flow itself starts over."""
    tr = Trace()
    with tr.step("Reading the catalogue") as s:
        cat = _books()
        s.detail = f"{len(cat)} catalogue-verified books on {len({e['line_id'] for e in cat})} reading paths"
    fresh = _fresh(state)
    if not text:
        return _clarify(tr, cat, "What would you like to read or learn?", state)
    if text.startswith("book:"):
        e = next((x for x in cat if x["id"] == text[5:]), None)
        if e:
            with tr.step("Checking the catalogue") as s:
                s.detail = f"{e['title']} · on a cached reading path"
            return _choose_book(fresh, _cand(e), tr.steps)
        text = text[5:]
    if text.startswith("topic:"):
        label = text[6:].strip()
        group = next((g for g in GROUPS if g[0].lower() == label.lower()), None)
        query = group[1] if group else label
        with tr.step("Understanding your request") as s:
            s.detail = f"topic: {label} · you picked it"
        hits = _search(tr, query, cat, frozenset(group[2]) if group else frozenset())
        res, why_not = _ask(tr, f"Books on {query}", hits, "Asking the model") if hits else (None, "")
        return _recommend(tr, fresh, cat, hits, _picked(tr, hits, res, why_not), label.lower() if group else label, label)
    if llm.needs_english(text):
        # Marathi, Hindi, Chinese, Tamil...: the catalogue is English books, so read the request in English
        with tr.step("Reading your language") as s:
            english = llm.english_query(text)
            s.detail = f"in English: {english}" if english else "couldn't read it right now"
        if not english:
            return _clarify(tr, cat, _say("unreadable"), state)
        text = english
    decided = rules(text, cat)
    if not decided:
        saved = _saved_path_for(text)
        if saved is not None:
            with tr.step("Understanding your request") as s:
                s.detail = f"title: {saved['title']} · a saved reading path"
            return _choose_book(fresh, saved, tr.steps)
    if decided:
        intent, how = decided
        with tr.step("Understanding your request") as s:
            s.detail = how
        if intent.kind == "unclear":
            return _clarify(tr, cat, "Happy to help. Let's narrow it down a little.", state)
        return _find_named(tr, fresh, cat, intent, text)
    # retrieval first, then one model call reads the request (and the chat so far) together with what we found
    hits = _search(tr, text, cat)
    res, why_not = _ask(tr, text, hits, "Understanding your request", state.history)
    if res is None:
        intent = heuristic_intent(text)
        if why_not == "no model":
            with tr.step("Understanding your request") as s:
                s.detail = f"topic: {intent.value[:60]} · keyword rules (no model)"
    else:
        intent = Intent(kind=res.kind, value=res.value.strip())
    if intent.kind == "unclear":
        return _clarify(tr, cat, "Happy to help. Let's narrow it down a little.", state)
    if intent.kind in ("title", "author"):
        nearest = validate_picks(res.picks, hits)[0] if res else None
        return _find_named(tr, fresh, cat, intent, text, nearest)
    return _recommend(tr, fresh, cat, hits, _picked(tr, hits, res, "" if why_not == "no model" else why_not), intent.value, text)


def _finish(state: ChatState) -> ChatReply:
    tr = Trace()
    with tr.step("Building your reading path") as s:
        route = load_route(state.book_id or "")
        if route is not None:
            target = next(x for x in route.stops if x.role == "target")
            level = state.level or 1
            focus = next((x for x in route.stops if x.book.id == state.focus_id), None) if state.focus_id else None
            before = [x for x in route.stops if x.role == "before" and x.readiness.level >= level]
            hours = sum(x.readiness.hours for x in before)
            start = focus if focus is not None and focus.role != "target" else (before[0] if before else target)
            s.detail = (f"{len(before)} {'book' if len(before) == 1 else 'books'} before {target.book.title} · about {round(hours)} h · cached path"
                        if before else f"{target.book.title} · ready to start · cached path")
    if route is None:
        return ChatReply(messages=["I couldn't build that reading path. Try searching for the title instead."], state=ChatState(), trace=tr.steps)
    state.step = "done"
    with tr.step("Checking shelves") as s:
        av = start.availability
        chosen = next((a for a in av if a.branch_code == state.branch), None) if state.branch else None
        if chosen and chosen.available > 0:
            status = f"available at {_short_branch(chosen.branch)} ({chosen.call_number})"
        else:
            best = max((a for a in av if a.available > 0), key=lambda a: a.available, default=None)
            status = f"available at {_short_branch(best.branch)} ({best.call_number})" if best else "all copies out — join the waiting list"
            if chosen and best:
                status = f"not on the shelf at {_short_branch(chosen.branch)}; {status}"
        where = _short_branch(BRANCHES.get(state.branch or "", "")) or "all libraries"
        s.detail = f"{start.book.title} at {where}: {status}"
    if focus is not None and focus.role != "target":
        lead = f"{start.book.title} is on the reading path to {target.book.title}, about {round(start.readiness.hours)} hours. It's {status}."
    elif before:
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
    # Tell the reader what the book is actually about (catalogue description), not only where it is.
    from .discover import blurb  # local import: discover imports heavier modules

    msgs = [lead]
    about = blurb(start.book.summary, limit=320)
    if about:
        msgs.append(f"About {start.book.title}: {about}")
    elif start.readiness.one_line:
        msgs.append(start.readiness.one_line)
    if start.readiness.assumed_concepts:
        msgs.append("It helps to know: " + ", ".join(start.readiness.assumed_concepts[:4]) + ".")
    result["start_about"] = about or ""
    # the books this answer talks about, so "is it at Tampines?" or "who wrote it?" can follow
    by_id = {e["id"]: e for e in _books()}
    state.shown = [_cand(by_id[i]) for i in dict.fromkeys([start.book.id, target.book.id]) if i in by_id] or state.shown
    return ChatReply(messages=msgs, state=state, result=result, trace=tr.steps)


HISTORY_TURNS = 6
_RESTART = ("start over", "restart", "reset")


def step(turn: ChatTurn) -> ChatReply:
    """Advance the chat one turn. Stateless: the client sends the whole turn state back each time,
    including the conversation memory, which this adds the turn to."""
    token = _LANG.set(turn.lang)
    try:
        reply = _step(turn)
    finally:
        _LANG.reset(token)
    if (turn.text or "").strip().lower() not in _RESTART:
        _remember(turn, reply)
    return reply


def _said(state: ChatState, text: str) -> str:
    """What the reader said, in words: a tapped option becomes its label."""
    if state.step == "pick" and text.isdigit() and int(text) < len(state.candidates):
        return state.candidates[int(text)]["title"]
    if state.step == "level" and text.isdigit():
        return next((label for label, v in LEVELS if v == text), text)
    if state.step == "branch" and (text in BRANCHES or not text):
        return _short_branch(BRANCHES[text]) if text else "Any library"
    if text.startswith("topic:"):
        return text[6:]
    if text.startswith("book:"):
        return next((e["title"] for e in _books() if e["id"] == text[5:]), text[5:])
    return text


def _remember(turn: ChatTurn, reply: ChatReply) -> None:
    said = _said(turn.state, (turn.text or "").strip())
    books = [o.label for o in reply.options if o.value.isdigit()]
    answer = " ".join(reply.messages) + (" Options: " + "; ".join(f"{i + 1}) {b}" for i, b in enumerate(books)) if books else "")
    turns = list(turn.state.history) + ([{"role": "reader", "text": said[:200]}] if said else []) + [{"role": "PreReads", "text": answer[:400]}]
    reply.state.history = turns[-HISTORY_TURNS:]


def _step(turn: ChatTurn) -> ChatReply:
    state = turn.state
    text = (turn.text or "").strip()

    if text.lower() in _RESTART:
        return ChatReply(messages=["Fresh start. What would you like to read about?"], state=ChatState())

    # a message about what's already on screen ("the second one", "who wrote it?", "something easier")
    if not (state.step == "level" and _level_in(text) is not None and not _PRONOUN_RE.search(text.lower())):
        follow = _followup(state, text)
        if follow is not None:
            return follow

    if state.step in ("start", "done") or (state.step == "pick" and not text.isdigit()):
        return _start(state, text)

    if state.step == "pick":
        i = int(text)
        if 0 <= i < len(state.candidates):
            return _choose_book(state, state.candidates[i])
        return ChatReply(messages=["Which of these would you like?"], options=[ChatOption(label=f"{h['title']} — {h['author']}", value=str(i)) for i, h in enumerate(state.candidates)], state=state)

    if state.step == "level":
        level = _level_in(text)
        if level is None:                 # not an answer to the question: a new request
            return _start(state, text)
        state.level = level
        return _ask_branch(state)

    if state.step == "branch":
        if text and text.lower() not in ("any", "anywhere", "any library") and _branch_in(text) is None:
            return _start(state, text)
        state.branch = _branch_in(text) if text else None
        return _finish(state)

    return ChatReply(messages=["What would you like to read about next?"], state=_fresh(state))


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
