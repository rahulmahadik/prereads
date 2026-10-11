"""Guided chat: free text in, a few questions, then a reading path + directions.

The flow is a small state machine (start -> pick -> level -> branch -> done) so it
behaves the same with or without the local model. The free-text step is
retrieval-augmented over our own data:

  understand  rules first (too vague? an exact title or author?), then the local model
  retrieve    nomic-embed-text over every catalogue-verified book on a cached path
              (discover._catalogue), keyword scoring as the fallback
  choose      the local model picks the best 3 FROM the retrieved list; any id outside
              it is dropped (never an unverified book); top 3 by score without a model
  shelves     reader-facing status for each option (demo data is labelled)

Every reply carries `trace`: the steps that actually ran, with real counts and timings.

Layer: services. Served by api/routes_chat.py (/api/chat); browse()/books_for() also back
/api/browse. Reuses services.discover's catalogue and scoring, so both features agree.
"""
from __future__ import annotations

import concurrent.futures as cf
import contextvars
import json
import logging
import os
import re
import time
from contextlib import contextmanager
from difflib import SequenceMatcher
from typing import Callable, Iterator, Literal, Optional

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
    candidates: list[dict] = Field(default_factory=list)
    level: Optional[int] = None
    branch: Optional[str] = None


class ChatOption(BaseModel):
    label: str
    value: str
    hint: str = ""                      # one line under the label: why it fits, shelf status


class ChatTurn(BaseModel):
    text: str
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


def stream(turn: "ChatTurn") -> Iterator[str]:
    """NDJSON stream: one line per real step event, then the final reply."""
    import json
    import queue
    import threading

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
    while True:
        line = q.get()
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


def match(text: str) -> list[dict]:
    """Keyword match over cached targets (kept for callers; the chat uses retrieval below)."""
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
    return Intent(kind="topic", value=" ".join(discover.heuristic_need(text).topics[:4]) or text.strip())


def understand(text: str, cat: list[dict]) -> tuple[Intent, str]:
    """Rules, else keyword parsing. (The model reads the request together with the retrieved books in ask_model.)"""
    return rules(text, cat) or (heuristic_intent(text), f"topic: {heuristic_intent(text).value[:60]} · keyword rules (no model)")


def parse_intent(text: str) -> Intent:
    return understand(text, _books())[0]


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


# ------------------------------------------------------------------ the local model (one call)
class Understood(BaseModel):
    kind: Literal["title", "author", "topic", "unclear"]
    value: str
    picks: list[Pick]


ASK_SYSTEM = (
    "You are PreReads, a public-library readers' advisor. REQUEST is the reader's message. CANDIDATES were "
    "retrieved from our library catalogue for it. 1) kind: title = they named a specific book; author = they "
    "named a writer; topic = a subject, question or need; unclear = a greeting or no subject at all. value: the "
    "book title, the author's name, or the subject in 1-4 plain words (e.g. 'investing', not 'understand investing'). "
    "2) picks: the 3 CANDIDATES that best answer the request, best first; for a beginner prefer a gentle start. "
    "reason: one plain, warm sentence to the reader, at most 14 words. Use only ids from CANDIDATES. Never invent a book."
)

_LANG: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar("chat_lang", default=None)
MODEL_BUDGET = float(os.getenv("CHAT_MODEL_BUDGET", "25"))   # seconds; past this the chat answers without the model
_pool = cf.ThreadPoolExecutor(max_workers=2, thread_name_prefix="chat-llm")


def ask_model(request: str, hits: list[tuple[dict, float, str]]) -> tuple[Optional[Understood], str]:
    """One local-model call: what the reader means, and the best 3 of the retrieved books. (None, why) on failure."""
    user = json.dumps({
        "REQUEST": request,
        "CANDIDATES": [{
            "id": e["id"], "title": e["title"], "author": e["author"], "level": e["level"], "hours": e["hours"],
            "about": [x for x in e["subjects"] + e["concepts"] if len(x.split()) <= 4][:6],
        } for e, _, _ in hits],
    }, ensure_ascii=False)
    fut = _pool.submit(llm.structured, Understood, llm.with_lang(ASK_SYSTEM, _LANG.get()), user, kind="chat", temperature=0.2)
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
        opts.append(ChatOption(label=p["title"], value=f"book:{p['id']}", hint="Popular right now" + (" · demo data" if p["demo"] else "")))
    detail = f"{len(counts)} subjects{' and the most wanted title' if pop else ''} from {len(cat)} books"
    if pop and pop[0]["demo"]:
        detail += " · demand is demo data"
    return opts, detail


def _status(e: dict) -> tuple[str, bool]:
    status, _ = discover.status_for(e, None)
    return status, any(a.demo for a in e["availability"])


def _book_option(i: int, e: dict, reason: str = "") -> ChatOption:
    status, _ = _status(e)
    hint = " · ".join(x for x in (reason, status) if x)
    return ChatOption(label=f"{e['title'].split(':')[0].strip()} — {e['author']}", value=str(i), hint=hint)


def _cand(e: dict) -> dict:
    return {"id": e["id"], "line_id": e["line_id"], "title": e["title"], "author": e["author"], "is_target": e["is_target"]}


def _shelf_step(tr: Trace, entries: list[dict]) -> None:
    with tr.step("Checking shelves") as s:
        on = 0
        demo = False
        for e in entries:
            status, d = _status(e)
            demo = demo or d
            on += status.startswith("Available")
        s.detail = f"{on} of {len(entries)} on a shelf now, across {len(BRANCHES)} libraries" + (" · demo data" if demo else "")


# ----------------------------------------------------------------------- flow
LEVELS = [("New to this", "1"), ("Read a bit", "3"), ("Know it well", "4")]


def _ask_level(state: ChatState, lead: str, trace: Optional[list[TraceStep]] = None) -> ChatReply:
    state.step = "level"
    state.candidates = []
    return ChatReply(messages=[lead, "How familiar are you with this topic?"], options=[ChatOption(label=l, value=v) for l, v in LEVELS], state=state, trace=trace or [])


def _ask_branch(state: ChatState) -> ChatReply:
    state.step = "branch"
    opts = [ChatOption(label="Any library", value="")] + [ChatOption(label=_short_branch(n), value=c) for c, n in BRANCHES.items()]
    return ChatReply(messages=["Which library will you go to? I'll check the shelf there."], options=opts, state=state)


def _choose_book(state: ChatState, c: dict, trace: Optional[list[TraceStep]] = None) -> ChatReply:
    state.book_id = c.get("line_id") or c["id"]
    state.focus_id = c["id"]
    lead = f"Got it: {c['title']} by {c['author']}."
    if not c.get("is_target"):
        line = _line_titles().get(c["line_id"])
        if line:
            lead += f" It's on the reading path to {line}."
    return _ask_level(state, lead, trace)


def _clarify(tr: Trace, cat: list[dict], lead: str) -> ChatReply:
    with tr.step("Looking at what we have") as s:
        opts, s.detail = starter_options(cat)
    return ChatReply(
        messages=[lead, "Pick a subject below, or tell me a topic, a title or an author you like."],
        options=opts, state=ChatState(), trace=tr.steps,
    )


def _offer(tr: Trace, state: ChatState, picks: list[tuple[dict, str]], messages: list[str]) -> ChatReply:
    _shelf_step(tr, [e for e, _ in picks])
    state.step = "pick"
    state.candidates = [_cand(e) for e, _ in picks]
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


def _ask(tr: Trace, request: str, hits: list[tuple[dict, float, str]], step_name: str) -> tuple[Optional[Understood], str]:
    if not config.llm_enabled():
        return None, "no model"
    with tr.step(step_name) as s:
        res, why_not = ask_model(request, hits)
        s.detail = (f"{res.kind}: {res.value.strip()} · local model {_model_name()}" if config.AI_PROVIDER == "ollama" else f"{res.kind}: {res.value.strip()} · {_model_name()}") if res else why_not
    return res, why_not


def _search(tr: Trace, query: str, cat: list[dict], cats: frozenset = frozenset()) -> list[tuple[dict, float, str]]:
    with tr.step("Searching the catalogue") as s:
        hits, method = retrieve(query, cat, cats=cats)
        s.detail = f"{len(hits)} {'match' if len(hits) == 1 else 'matches'} from {len(cat)} books ({method})"
    return hits


def _recommend(tr: Trace, state: ChatState, cat: list[dict], hits: list[tuple[dict, float, str]], picks: list[tuple[dict, str]], label: str, request: str) -> ChatReply:
    if not hits or not picks:
        return _clarify(tr, cat, f"I couldn't find '{request.strip()}' in the catalogue yet. Here's what I can help with.")
    about = " ".join(w for w in label.split() if w.lower() not in _FILLER) or label
    about = about if len(about) <= 40 else "that"
    weak = hits[0][1] < 0.62
    lead = f"I don't have much on {about}, but these come closest." if weak else f"Here are {len(picks)} good places to start on {about}."
    return _offer(tr, state, picks, [lead, "Tap one to see what to read first and where it is."])


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
        return _offer(tr, state, picks, [f"I have {len(hits)} books by {who}. Which one?" if intent.kind == "author" else "A few books match. Which one did you mean?"])
    # not held: offer the nearest books we do hold, by meaning
    if not nearest:
        with tr.step("Finding the closest books") as s:
            near, method = retrieve(f"{intent.value} {text}", cat, k=3)
            s.detail = f"{len(near)} nearest from {len(cat)} books ({method})"
        nearest = top_by_score(near)
    if not nearest:
        return _clarify(tr, cat, f"I couldn't find '{intent.value}' in the catalogue yet. Here's what I can help with.")
    return _offer(tr, state, nearest, [f"I couldn't find '{intent.value}' in the catalogue yet.", "These are the closest books I have:"])


def _start(state: ChatState, text: str) -> ChatReply:
    tr = Trace()
    with tr.step("Reading the catalogue") as s:
        cat = _books()
        s.detail = f"{len(cat)} catalogue-verified books on {len({e['line_id'] for e in cat})} reading paths"
    fresh = ChatState()
    if not text:
        return _clarify(tr, cat, "What would you like to read or learn?")
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
        res, why_not = _ask(tr, f"Books on {query}", hits, "Asking the local model") if hits else (None, "")
        return _recommend(tr, fresh, cat, hits, _picked(tr, hits, res, why_not), label.lower() if group else label, label)
    decided = rules(text, cat)
    if decided:
        intent, how = decided
        with tr.step("Understanding your request") as s:
            s.detail = how
        if intent.kind == "unclear":
            return _clarify(tr, cat, "Happy to help. Let's narrow it down a little.")
        return _find_named(tr, fresh, cat, intent, text)
    # retrieval first, then one model call reads the request together with what we found
    hits = _search(tr, text, cat)
    res, why_not = _ask(tr, text, hits, "Understanding your request")
    if res is None:
        intent = heuristic_intent(text)
        if why_not == "no model":
            with tr.step("Understanding your request") as s:
                s.detail = f"topic: {intent.value[:60]} · keyword rules (no model)"
    else:
        intent = Intent(kind=res.kind, value=res.value.strip())
    if intent.kind == "unclear":
        return _clarify(tr, cat, "Happy to help. Let's narrow it down a little.")
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
        s.detail = f"{start.book.title} at {where}: {status}" + (" · demo data" if any(a.demo for a in av) else "")
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
    msgs.append("Open it for the description, a free sample or first chapter where available, and the walk to the shelf.")
    result["start_about"] = about or ""
    return ChatReply(messages=msgs, state=state, result=result, trace=tr.steps)


def step(turn: ChatTurn) -> ChatReply:
    """Advance the chat one turn. Stateless: the client sends the whole turn state back each time."""
    token = _LANG.set(turn.lang)
    try:
        return _step(turn)
    finally:
        _LANG.reset(token)


def _step(turn: ChatTurn) -> ChatReply:
    state = turn.state
    text = (turn.text or "").strip()

    if text.lower() in ("start over", "restart", "reset"):
        return ChatReply(messages=["Fresh start. Tell me a book, an author, or something you want to learn."], state=ChatState())

    if state.step in ("start", "done") or (state.step == "pick" and not text.isdigit()):
        return _start(ChatState(), text)

    if state.step == "pick":
        i = int(text)
        if 0 <= i < len(state.candidates):
            return _choose_book(state, state.candidates[i])
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
