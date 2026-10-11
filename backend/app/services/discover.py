"""Discovery: a reader's sentence in, ranked and filterable recommendations out.

    "I want to understand investing but I only have two weeks"
    -> Need{topics:[investing], max_hours:10, level:1, ...}
    -> candidates (LLM-proposed, catalogue-verified) + cached targets that match
    -> scored for fit (topic, level, time, availability at the reader's branch)
    -> filter chips generated from the need and the result set

Two phases, so a reader never stares at a spinner:
  fast  no model call, no network: heuristic need + the local embedding shortlist (with a
        time budget) + keyword score over the cached catalogue. Well under a second.
  deep  the local model reads the need and proposes books, each verified in the catalogue,
        merged with the catalogue results (and, live, catalogue search pages). Seconds to tens
        of seconds; the UI runs it in the background and adds its picks as "AI pick".
With the AI off, a heuristic parser handles the common phrasings so the demo still feels
intelligent, and the recommendations are drawn from the precomputed catalogue.

Layer: services. Served by api/routes_discover.py (/api/discover, /api/similar); services.chat
reuses its catalogue and scoring. Uses ai.llm + ai.embeddings, integrations.catalog to verify.
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Literal, Optional

from pydantic import BaseModel, Field

from ..core import config
from ..ai import embeddings, llm
from ..integrations.availability import BRANCHES, get_availability, get_demand
from ..integrations.catalog import nlb, openlibrary_search_many, resolve
from .engine import heuristic_readiness
from .reading_age import estimate as estimate_age, heuristic as age_heuristic
from .engine import load_route, score_readiness, seeds

log = logging.getLogger("prereads.discover")


class Need(BaseModel):
    summary: str = ""                              # one line: what the reader wants
    topics: list[str] = Field(default_factory=list)
    level: Optional[int] = None                    # 1-5 reader readiness
    max_hours: Optional[float] = None
    age_group: Optional[Literal["child", "teen", "adult"]] = None
    language: Optional[str] = None
    mood: Optional[str] = None                     # e.g. "practical", "story-driven"
    format: Optional[Literal["book", "ebook", "audio"]] = None


class Proposed(BaseModel):
    title: str
    author: str
    why: str


class Proposal(BaseModel):
    need: Need
    books: list[Proposed]


class FilterChip(BaseModel):
    id: str
    label: str
    kind: Literal["level", "hours", "branch", "category", "language", "age"]
    value: str
    on: bool = False


class Recommendation(BaseModel):
    id: str
    line_id: str
    is_target: bool
    title: str
    author: str
    category: str
    level: int
    hours: float
    why: str
    fit: float
    status: str                                    # reader-facing
    available_at: list[str]
    hot_at: list[str]
    before_count: int
    reading_age: Optional[str] = None
    blurb: Optional[str] = None                    # two-line plain description from the catalogue
    min_age: Optional[int] = None
    ai_pick: bool = False                          # proposed by the model (deep phase), then catalogue-verified


class DiscoverRequest(BaseModel):
    text: str
    branch: Optional[str] = None
    filters: list[str] = Field(default_factory=list)   # chip ids that are on
    offset: int = 0
    limit: int = 10
    mode: Literal["fast", "deep"] = "fast"             # fast: no model, no network; deep: model proposals too
    lang: Optional[str] = None                         # reader's UI language: AI-written reasons follow it


class DiscoverResponse(BaseModel):
    need: Need
    chips: list[FilterChip]
    results: list[Recommendation]
    engine: str                                    # "fast" | "llm" | "heuristic"
    total: int = 0
    offset: int = 0
    limit: int = 10
    has_more: bool = False
    deep: Optional[Literal["ai", "catalogue"]] = None   # fast only: what a deep pass would add (None = nothing)
    timings_ms: dict[str, float] = Field(default_factory=dict)


# ------------------------------------------------------------------ parsing
_LEVEL_WORDS = [
    (("beginner", "new to", "never", "no background", "from scratch", "simple", "easy", "start"), 1),
    (("some", "a bit", "read a few", "intermediate"), 3),
    (("advanced", "expert", "deep", "rigorous", "graduate", "know it well", "professional"), 4),
]
_AGE_WORDS = [(("kid", "child", "children", "year-old", "year old", "primary", "son", "daughter"), "child"), (("teen", "secondary", "teenager"), "teen")]
_LANG_WORDS = {"chinese": "Chinese", "mandarin": "Chinese", "malay": "Malay", "tamil": "Tamil", "english": "English"}
_MOOD_WORDS = [(("practical", "hands-on", "how to", "apply"), "practical"), (("story", "narrative", "fun", "entertaining"), "story-driven"), (("short", "quick", "fast"), "quick")]


def heuristic_need(text: str) -> Need:
    """Need from keyword rules (level, age, language, mood, time words). No model, no network."""
    t = text.lower()
    need = Need(summary=text.strip())
    for words, lvl in _LEVEL_WORDS:
        if any(w in t for w in words):
            need.level = lvl
    for words, age in _AGE_WORDS:
        if any(w in t for w in words):
            need.age_group = age
    m = re.search(r"(\d+)\s*(hour|hr|h)\b", t)
    if m:
        need.max_hours = float(m.group(1))
    m = re.search(r"(\d+)\s*(week|wk)", t)
    if m:
        need.max_hours = float(m.group(1)) * 5      # ~5 reading hours a week
    m = re.search(r"(\d+)\s*(day)", t)
    if m:
        need.max_hours = float(m.group(1)) * 1
    if "weekend" in t:
        need.max_hours = 6
    for k, v in _LANG_WORDS.items():
        if k in t:
            need.language = v
    for words, mood in _MOOD_WORDS:
        if any(w in t for w in words):
            need.mood = mood
    if "audio" in t:
        need.format = "audio"
    elif "ebook" in t or "e-book" in t or "kindle" in t:
        need.format = "ebook"
    stop = {"i", "want", "to", "a", "an", "the", "and", "but", "only", "have", "about", "for", "of", "in", "on", "with", "me", "my", "some", "something", "book", "books", "read", "learn", "understand", "understanding", "that", "is", "are", "weeks", "week", "hours", "hour", "beginner", "new", "this", "it", "please", "can", "you", "recommend", "suggest", "like", "love", "loves", "who", "old", "year", "years", "know", "knows", "already"}
    need.topics = [w for w in re.sub(r"[^a-z0-9 ]", " ", t).split() if w not in stop and (len(w) > 2 or w in _SYN) and not w.isdigit()][:6]
    return need


PROPOSE_SYSTEM = (
    "You are a public-library readers' advisor in Singapore. Read the reader's request. "
    "First fill `need`: a one-line summary, 1-4 topics, reader level 1-5 if implied, a time "
    "budget in hours if implied (a week ≈ 5 reading hours), age_group if implied, language, "
    "mood (practical / story-driven / quick / rigorous) and format if mentioned. Then propose "
    "8 real, widely available books that fit, ordered by fit, each with author and a one-sentence "
    "why written to this reader. Prefer books in a large public library. No inventions."
)


# Small in-process caches so a deep re-run for the same request (a filter toggle) skips the
# model call and the per-book catalogue checks. Successes only; bounded; keyed by mode.
_CACHE_MAX = 64
_cache_lock = threading.Lock()
_PROPOSALS: "OrderedDict[str, tuple[Need, list[Proposed]]]" = OrderedDict()
_VERIFIED: "OrderedDict[str, tuple[object, object]]" = OrderedDict()


def _cache_get(store: OrderedDict, key: str):
    with _cache_lock:
        hit = store.get(key)
        if hit is not None:
            store.move_to_end(key)
        return hit


def _cache_put(store: OrderedDict, key: str, value, cap: int = _CACHE_MAX) -> None:
    with _cache_lock:
        store[key] = value
        store.move_to_end(key)
        while len(store) > cap:
            store.popitem(last=False)


def propose(text: str, lang: Optional[str] = None) -> tuple[Need, list[Proposed], str]:
    """(need, unverified proposals, engine). Deep phase only; falls back to heuristic_need with no
    proposals when the model is off or fails. Proposals still have to pass resolve() before showing."""
    if config.llm_enabled():
        key = f"{config.mode()}|{(lang or 'en')[:2]}|{' '.join(text.lower().split())}"
        hit = _cache_get(_PROPOSALS, key)
        if hit is not None:
            return hit[0].model_copy(deep=True), list(hit[1]), "llm"
        p = llm.structured(Proposal, llm.with_lang(PROPOSE_SYSTEM, lang), text, temperature=llm.TEMP_PROPOSE)
        if p:
            if not p.need.summary:
                p.need.summary = text.strip()
            _cache_put(_PROPOSALS, key, (p.need.model_copy(deep=True), list(p.books)))
            return p.need, p.books, "llm"
    return heuristic_need(text), [], "heuristic"


# Open Library mixes format and shelving tags into subjects, and lists merchandising SKUs as books.
_JUNK_SUBJECT = re.compile(r"(daisy|accessible book|in library|lending library|overdrive|large type|braille|nyt:|protected|internet archive|open library|staff picks|reading level|fiction, general|open_syllabus|_|long now manual|new york times|^nonfiction$|^fiction$|^general$|textbooks?$|^history$|^science$)", re.I)
_JUNK_TITLE = re.compile(r"(counter display|\d+-copy|prepack|pre-pack|box set|boxed set|pack of \d+|summary of|study guide|workbook for|sparknotes|cliffsnotes|\bcopy\b)", re.I)


def clean_category(subjects: list[str], default: str) -> str:
    """First subject that reads like a topic (not a format or shelving tag)."""
    for x in subjects or []:
        if x and not _JUNK_SUBJECT.search(x) and len(x.split()) <= 5:
            return x
    return default


def junk_title(title: str) -> bool:
    return bool(_JUNK_TITLE.search(title or ""))


def blurb(summary: Optional[str], limit: int = 220) -> Optional[str]:
    """A short, plain description for result cards: catalogue text without markdown, links or
    edition notes, cut at a sentence (or word) boundary."""
    if not summary:
        return None
    text = re.split(r"^\s*[-=*_]{3,}\s*$", summary, maxsplit=1, flags=re.M)[0]
    text = re.sub(r"\[([^\]]+)\]\[\d+\]|\[([^\]]+)\]\([^)]*\)", lambda m: m.group(1) or m.group(2), text)
    text = re.sub(r"https?://\S+|[*_`#>]+|\(\s*\[?source\]?[^)]*\)", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text).strip().strip('"')
    if len(text) < 40:
        return None
    if len(text) <= limit:
        return text
    cut = text[:limit]
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: end + 1] if end > 80 else cut.rsplit(" ", 1)[0] + "…").strip()


# ------------------------------------------------------------------ catalogue
def _catalogue() -> list[dict]:
    """Every book on every cached line is a candidate; each remembers its line."""
    out: dict[str, dict] = {}
    for s in seeds():
        sid = s.get("isbn") or s.get("id")
        route = load_route(sid)
        if not route:
            continue
        before = [x for x in route.stops if x.role == "before"]
        category = (s.get("subjects") or ["Other"])[0]
        for stop in route.stops:
            b = stop.book
            if junk_title(b.title):
                continue
            entry = out.get(b.id)
            if entry and entry["is_target"]:
                continue
            out[b.id] = {
                "id": b.id,
                "line_id": sid,
                "is_target": stop.role == "target",
                "title": b.title,
                "author": b.author,
                "subjects": b.subjects or s.get("subjects", []),
                "category": category,
                "level": stop.readiness.level,
                "hours": stop.readiness.hours,
                "concepts": stop.readiness.assumed_concepts,
                "one_line": stop.readiness.one_line or (stop.why if stop.role != "target" else ""),
                "blurb": blurb(b.summary),
                "availability": stop.availability,
                "hot": stop.demand.hot_branches,
                "before_count": len([x for x in before if x.readiness.level < stop.readiness.level]) if stop.role == "target" else 0,
                "before_titles": [x.book.title.lower() for x in before],
                "after_titles": [x.book.title.lower() for x in route.stops if x.role == "after"],
            }
    return list(out.values())


_SYN = {
    "universe": {"cosmology", "physics", "time", "space"}, "space": {"cosmology", "physics"}, "stars": {"cosmology"},
    "money": {"investing", "finance", "economics"}, "stocks": {"investing", "stock", "market"}, "invest": {"investing"}, "investing": {"investing", "finance"},
    "rich": {"investing", "finance", "habits"}, "wealth": {"investing", "economics", "nations"},
    "brain": {"psychology", "cognition", "decision"}, "thinking": {"psychology", "decision", "cognition"}, "decisions": {"decision", "psychology"}, "decide": {"decision"},
    "bias": {"psychology", "decision"}, "mind": {"psychology", "consciousness"},
    "computer": {"computer", "software", "algorithms", "machine"}, "coding": {"software", "programming", "algorithms"}, "programming": {"software", "algorithms", "programming"},
    "ai": {"machine", "learning", "artificial", "neural"}, "artificial": {"machine", "learning"}, "neural": {"machine", "learning", "neural"},
    "history": {"history", "world", "singapore"}, "human": {"history", "evolution", "anthropology"}, "humans": {"history", "evolution"},
    "evolution": {"evolution", "biology", "gene"}, "genes": {"gene", "genetics", "evolution"}, "biology": {"evolution", "biology", "gene"},
    "philosophy": {"philosophy", "stoicism", "science"}, "stoic": {"stoicism", "philosophy"}, "calm": {"stoicism", "philosophy"},
    "habits": {"habits", "behavior"}, "productivity": {"habits", "deep", "work"}, "sleep": {"sleep", "neuroscience"},
    "health": {"health", "sleep", "medicine", "cancer"}, "cancer": {"cancer", "medicine"},
    "singapore": {"singapore", "history", "memoir"}, "economy": {"economics", "capital"}, "economics": {"economics", "capital", "inequality"},
    "randomness": {"probability", "randomness", "risk"}, "risk": {"risk", "probability", "finance"}, "luck": {"probability", "randomness"},
    "maths": {"mathematics", "logic", "algorithms"}, "math": {"mathematics", "logic"}, "logic": {"logic", "mathematics"},
    "systems": {"systems", "complexity"}, "secrets": {"cryptography"}, "codes": {"cryptography"}, "security": {"cryptography", "software"},
    "database": {"databases", "data"}, "databases": {"databases", "data"}, "architecture": {"software", "architecture", "design"},
    "devops": {"devops", "management"}, "science": {"science", "physics", "philosophy"},
}


def _tokens(s: str) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if len(t) > 2 or t in _SYN}


def _expand(tokens: set[str]) -> set[str]:
    out = set(tokens)
    for t in tokens:
        out |= _SYN.get(t, set())
        if t.endswith("s") and t[:-1] in _SYN:
            out |= _SYN[t[:-1]]
    return out


# ------------------------------------------------------------------ scoring
def semantic_topic(sim: float) -> float:
    """Centred nomic-embed-text cosine -> topic strength. Unrelated ~0, a clear match ~0.25.
    Capped at 0.8 so an explicit keyword or model-proposed match (1.0) still ranks first."""
    return max(0.0, min(0.8, (sim - 0.10) / 0.15))


def entry_text(e: dict) -> str:
    return f"{e['title']} by {e['author']}. {e['category']}. {', '.join(e['subjects'])}. {', '.join(e['concepts'])}. {e['one_line']}"


def score(entry: dict, need: Need, proposed_titles: dict[str, str], branch: Optional[str], semantic: float = 0.0) -> tuple[float, str]:
    """Return (fit 0-1, why). Topic match carries most weight; then level, time, branch.
    `semantic` is the embedding similarity strength; the keyword matcher still runs and the stronger signal wins."""
    why = ""
    topic = 0.0
    tt = _tokens(entry["title"]) | _tokens(" ".join(entry["subjects"])) | _tokens(" ".join(entry["concepts"]))
    nt = set()
    for t in need.topics:
        nt |= _tokens(t)
    nt = _expand(nt)
    tt = _expand(tt)
    if nt:
        hits = nt & tt
        topic = min(1.0, len(hits) / 2)          # two overlapping concepts = a confident match
    topic = max(topic, semantic)
    # A request often names several things ("AI ... Python"): a book covering all of them
    # beats one that matches a single topic, so scale by how many asked-for topics it covers.
    groups = [g for g in (_expand(_tokens(t)) for t in need.topics) if g]
    if len(groups) > 1 and topic > 0:
        # compare against the book's own words (not synonym-expanded), or "computer" → "machine"
        # would make every programming book look like it covers "AI"
        own = _tokens(entry["title"]) | _tokens(" ".join(entry["subjects"])) | _tokens(" ".join(entry["concepts"]))
        covered = sum(1 for g in groups if g & own)
        topic *= 0.6 + 0.4 * covered / len(groups)
    key = entry["title"].lower()
    if key in proposed_titles:
        topic = max(topic, 1.0)
        why = proposed_titles[key]
    # a cached line whose before/after books were proposed also counts
    elif any(b in proposed_titles for b in entry["before_titles"] + entry["after_titles"]):
        topic = max(topic, 0.7)
    if topic == 0:
        return 0.0, why

    level_fit = 1.0
    if need.level:
        gap = entry["level"] - need.level
        level_fit = 1.0 if gap <= 0 else max(0.2, 1 - 0.3 * gap)
    time_fit = 1.0
    if need.max_hours:
        time_fit = 1.0 if entry["hours"] <= need.max_hours else max(0.2, need.max_hours / entry["hours"])
    branch_fit = 1.0
    if branch:
        a = next((x for x in entry["availability"] if x.branch_code == branch), None)
        branch_fit = 1.0 if a and a.available > 0 else 0.7
    fit = 0.5 * topic + 0.2 * level_fit + 0.2 * time_fit + 0.1 * branch_fit
    if not why:
        bits = []
        if need.level and entry["level"] <= need.level:
            bits.append("pitched at your level")
        elif need.level and entry["level"] > need.level:
            n = entry["before_count"]
            bits.append(f"a step up — {n} {'book' if n == 1 else 'books'} to read first" if n else "a step up")
        if need.max_hours and entry["hours"] <= need.max_hours:
            bits.append(f"fits your {round(need.max_hours)} h")
        if branch and branch_fit == 1.0:
            bits.append(f"on the shelf at {BRANCHES.get(branch, branch).replace(' Public Library', '').replace(' Regional Library', '').replace(' Library', '')}")
        why = (entry["one_line"] or "A strong match for what you asked.") + (" " + ", ".join(bits).capitalize() + "." if bits else "")
    return round(fit, 3), why


def status_for(entry: dict, branch: Optional[str]) -> tuple[str, list[str]]:
    """Reader-facing shelf status for the reader's branch, plus the short names of branches that have it in."""
    av = entry["availability"]
    in_stock = [a for a in av if a.available > 0]
    names = [a.branch.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for a in in_stock]
    if branch:
        a = next((x for x in av if x.branch_code == branch), None)
        if a and a.available > 0:
            return f"Available at {a.branch.replace(' Public Library', '').replace(' Regional Library', '').replace(' Library', '')}", names
        if in_stock:
            return f"Not there — nearest at {names[0]}", names
    if in_stock:
        return f"Available at {names[0]}", names
    return "All out — join the waiting list", names


# ------------------------------------------------------------------ chips
def build_chips(need: Need, results: list[Recommendation], branch: Optional[str], on: set[str]) -> list[FilterChip]:
    chips: list[FilterChip] = []
    if need.level:
        chips.append(FilterChip(id=f"level:{need.level}", label=f"Level {need.level} or easier", kind="level", value=str(need.level)))
    if need.max_hours:
        chips.append(FilterChip(id=f"hours:{int(need.max_hours)}", label=f"Under {int(need.max_hours)} hours", kind="hours", value=str(int(need.max_hours))))
    else:
        chips.append(FilterChip(id="hours:10", label="Under 10 hours", kind="hours", value="10"))
    if branch:
        chips.append(FilterChip(id=f"branch:{branch}", label=f"On shelf at {BRANCHES.get(branch, branch).replace(' Public Library', '').replace(' Regional Library', '').replace(' Library', '')}", kind="branch", value=branch))
    else:
        chips.append(FilterChip(id="branch:any", label="On a shelf now", kind="branch", value="any"))
    cats = []
    for r in results[:6]:
        if r.fit >= 0.8 and r.category not in cats:
            cats.append(r.category)
    for c in cats[:4]:
        chips.append(FilterChip(id=f"category:{c}", label=c, kind="category", value=c))
    if need.age_group:
        chips.append(FilterChip(id=f"age:{need.age_group}", label={"child": "For children", "teen": "For teens", "adult": "For adults"}[need.age_group], kind="age", value=need.age_group, on=True))
    if need.language:
        chips.append(FilterChip(id=f"language:{need.language}", label=f"In {need.language}", kind="language", value=need.language))
    for ch in chips:
        if ch.id in on:
            ch.on = True
    # A chip that is on but this phase did not generate (the reader turned on a chip the deep
    # phase found, then the fast phase re-ran) still filters and still shows.
    have = {ch.id for ch in chips}
    for cid in sorted(on):
        if cid not in have:
            ch = chip_from_id(cid)
            if ch is not None:
                ch.on = True
                chips.append(ch)
    return chips


def chip_from_id(cid: str) -> Optional[FilterChip]:
    """Rebuild a chip from its id ("kind:value"); None for anything malformed."""
    kind, _, value = cid.partition(":")
    if not value:
        return None
    if kind == "level" and value.isdigit() and 1 <= int(value) <= 5:
        return FilterChip(id=cid, label=f"Level {value} or easier", kind="level", value=value)
    if kind == "hours":
        try:
            float(value)
        except ValueError:
            return None
        return FilterChip(id=cid, label=f"Under {value} hours", kind="hours", value=value)
    if kind == "branch":
        label = "On a shelf now" if value == "any" else f"On shelf at {BRANCHES.get(value, value).replace(' Public Library', '').replace(' Regional Library', '').replace(' Library', '')}"
        return FilterChip(id=cid, label=label, kind="branch", value=value)
    if kind == "category":
        return FilterChip(id=cid, label=value, kind="category", value=value)
    if kind == "age" and value in ("child", "teen", "adult"):
        return FilterChip(id=cid, label={"child": "For children", "teen": "For teens", "adult": "For adults"}[value], kind="age", value=value)
    if kind == "language":
        return FilterChip(id=cid, label=f"In {value}", kind="language", value=value)
    return None


def _age_fields(a: dict) -> dict:
    tag = a["label"] + (" · estimated" if a["source"] == "estimated" else "")
    return {"reading_age": tag, "min_age": a["min_age"]}


def apply_filters(results: list[Recommendation], chips: list[FilterChip]) -> list[Recommendation]:
    out = results
    for ch in chips:
        if not ch.on:
            continue
        if ch.kind == "level":
            out = [r for r in out if r.level <= int(ch.value)]
        elif ch.kind == "hours":
            out = [r for r in out if r.hours <= float(ch.value)]
        elif ch.kind == "branch":
            out = [r for r in out if r.available_at] if ch.value == "any" else [r for r in out if r.status.startswith("Available")]
        elif ch.kind == "category":
            out = [r for r in out if r.category == ch.value]
        elif ch.kind == "age":
            cap = {"child": 11, "teen": 17}.get(str(ch.value), 99)   # a teen can read a "12+" book; a child cannot
            out = [r for r in out if r.min_age is None or r.min_age <= cap]
        # language: the demo catalogue is adult English; keep results and let the UI say so
    return out


def _catalogue_search(need: Need, branch: Optional[str], page: int, size: int) -> list[Recommendation]:
    """Live mode only: more candidates straight from the catalogue, scored heuristically.
    Keeps the list broad (a library, not a shortlist); the LLM scores a book properly when opened."""
    if config.effective_demo():
        return []
    keywords = " ".join(need.topics[:3]) or need.summary
    books = []
    if nlb().enabled():
        data = nlb()._get("SearchTitles", Keywords=keywords, Limit=size, Offset=page * size)
        for t in (data or {}).get("titles", []) or []:
            try:
                books.append(nlb().to_book(t))
            except Exception:  # noqa: BLE001
                continue
    else:
        books = openlibrary_search_many(keywords, page=page + 1, size=size)
    out: list[Recommendation] = []
    books = [b for b in books if not junk_title(b.title)]
    for i, b in enumerate(books):
        rd = heuristic_readiness(b)
        av = get_availability(b)
        dm = get_demand(b, av)
        status, names = status_for({"availability": av}, branch)
        level_fit = 1.0 if not need.level else (1.0 if rd.level <= need.level else max(0.2, 1 - 0.3 * (rd.level - need.level)))
        time_fit = 1.0 if not need.max_hours else (1.0 if rd.hours <= need.max_hours else max(0.2, need.max_hours / rd.hours))
        fit = round(0.55 * (1 - i / max(1, len(books) * 2)) + 0.25 * level_fit + 0.2 * time_fit, 3)
        out.append(Recommendation(
            id=b.id, line_id=b.id, is_target=True, title=b.title, author=b.author, category=clean_category(b.subjects, "Catalogue"),
            level=rd.level, hours=rd.hours, why=(b.summary[:160] + "…") if b.summary else "From the catalogue search for your topic.",
            fit=min(0.89, fit), status=status, available_at=names,
            hot_at=[h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in dm.hot_branches], before_count=0,
            blurb=blurb(b.summary), **_age_fields(estimate_age(b, rd)),
        ))
    return out


# ------------------------------------------------------------------ entry
FAST_EMBED_BUDGET_S = 0.35     # fast phase: the query embedding must answer within this, else keywords only
_embed_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="discover-embed")


_QVEC: "OrderedDict[str, list[float]]" = OrderedDict()


def _rank_fast(query: str, items: list[tuple[str, str]], top_k: int = 40) -> Optional[list[tuple[str, float]]]:
    """embeddings.rank without its disk write: the catalogue vectors come from the on-disk cache, and a
    new query's vector is kept in memory only (rank() re-writes the whole multi-MB cache file per new query)."""
    if not items:
        return []
    d = embeddings.vectors([t for _, t in items])        # cached; no model call once warm
    if d is None:
        return None
    q = _cache_get(_QVEC, query)
    if q is None:
        got = llm.embed(["search_query: " + query])       # local Ollama, ~20-50 ms warm
        if not got:
            return None
        q = got[0]
        _cache_put(_QVEC, query, q, cap=_CACHE_MAX * 4)
    n = len(d)
    mean = [sum(col) / n for col in zip(*d)]              # same mean-centring as embeddings.rank
    qc = [a - m for a, m in zip(q, mean)]
    scored = [(i, embeddings.cosine(qc, [a - m for a, m in zip(v, mean)])) for (i, _), v in zip(items, d)]
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def _shortlist(need: Need, cat: list[dict], budget: Optional[float]) -> tuple[dict[str, float], str]:
    """Embedding similarity per catalogue id (local nomic-embed-text). With a budget the call runs
    in a worker and is abandoned when slow (a cold model load); it still finishes and warms the cache."""
    query = " ".join([need.summary] + need.topics)
    items = [(e["id"], entry_text(e)) for e in cat]
    if budget is None:
        ranked = embeddings.rank(query, items, top_k=40)
    else:
        fut = _embed_pool.submit(_rank_fast, query, items, 40)
        try:
            ranked = fut.result(timeout=budget)
        except FutureTimeout:
            return {}, "slow"
        except Exception:  # noqa: BLE001
            return {}, "error"
    return (dict(ranked), "on") if ranked is not None else ({}, "off")


def _from_catalogue(cat: list[dict], need: Need, proposed_titles: dict[str, str], branch: Optional[str], sims: dict[str, float]) -> list[Recommendation]:
    out: list[Recommendation] = []
    for e in cat:
        fit, why = score(e, need, proposed_titles, branch, semantic_topic(sims.get(e["id"], 0.0)))
        if fit <= 0:
            continue
        status, names = status_for(e, branch)
        proposed_here = e["title"].lower() in proposed_titles
        out.append(Recommendation(
            id=e["id"], line_id=e["line_id"], is_target=e["is_target"], title=e["title"], author=e["author"], category=e["category"], level=e["level"], hours=e["hours"],
            why=why, fit=fit, status=status, available_at=names, hot_at=[h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in e["hot"]],
            before_count=e["before_count"], ai_pick=proposed_here, blurb=e.get("blurb"), **_age_fields(age_heuristic([], [], e["level"], None)),
        ))
    return out


def _verify(pr: Proposed):
    """Catalogue check + readiness for one model proposal (network and model; deep phase only). Cached."""
    key = f"{config.mode()}|{pr.title.lower()}|{pr.author.lower()}"
    hit = _cache_get(_VERIFIED, key)
    if hit is not None:
        return hit
    b = resolve(pr.title, pr.author)
    if b is None or junk_title(b.title):
        return None
    rd, _ = score_readiness(b)
    _cache_put(_VERIFIED, key, (b, rd), cap=_CACHE_MAX * 4)
    return b, rd


def _from_proposals(proposed: list[Proposed], results: list[Recommendation], branch: Optional[str]) -> list[Recommendation]:
    """Books the model proposed that are not on any cached line, verified in the catalogue
    (their line is built when opened). Checked in parallel; added in the model's order."""
    have = {r.title.lower() for r in results}
    todo = [(i, pr) for i, pr in enumerate(proposed[:8]) if pr.title.lower() not in have]
    if not todo:
        return []
    with ThreadPoolExecutor(max_workers=4, thread_name_prefix="discover-verify") as pool:
        verified = list(pool.map(lambda x: _safe_verify(x[1]), todo))
    out: list[Recommendation] = []
    for (i, pr), got in zip(todo, verified):
        if got is None:
            continue
        b, rd = got
        if b.title.lower() in have:
            continue
        av = get_availability(b)
        dm = get_demand(b, av)
        status, names = status_for({"availability": av}, branch)
        out.append(Recommendation(
            id=b.id, line_id=b.id, is_target=True, title=b.title, author=b.author,
            category=clean_category(b.subjects, "Suggested"), level=rd.level, hours=rd.hours, why=pr.why,
            fit=round(max(0.5, 0.95 - 0.04 * i), 3), status=status, available_at=names,
            hot_at=[h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in dm.hot_branches],
            before_count=0, ai_pick=True, blurb=blurb(b.summary), **_age_fields(estimate_age(b, rd)),
        ))
        have.add(b.title.lower())
    return out


def _safe_verify(pr: Proposed):
    try:
        return _verify(pr)
    except Exception as exc:  # noqa: BLE001 - one bad proposal never sinks the list
        log.warning("proposal check failed for %r: %s", pr.title, exc)
        return None


def deep_offer() -> Optional[str]:
    """What a deep pass would add over the fast one: model picks, catalogue pages, or nothing."""
    if config.llm_enabled():
        return "ai"
    if not config.effective_demo():
        return "catalogue"
    return None


def discover(req: DiscoverRequest) -> DiscoverResponse:
    """One page of recommendations for the reader's sentence (see the module docstring for
    the two phases). Every result is a cached catalogue entry or a catalogue-verified proposal."""
    t0 = time.perf_counter()
    timings: dict[str, float] = {}

    def lap(name: str, since: float) -> float:
        now = time.perf_counter()
        timings[name] = round((now - since) * 1000, 1)
        return now

    # The split: fast must answer in well under a second with no model and no network, so
    # the screen fills at once; the client then calls again with mode="deep" in the background
    # (only when deep_offer() says it would add something) and merges the extra picks.
    fast = req.mode == "fast"
    if fast:
        need, proposed, engine = heuristic_need(req.text), [], "fast"
    else:
        need, proposed, engine = propose(req.text, req.lang)
    t = lap("need", t0)
    proposed_titles = {p.title.lower(): p.why for p in proposed}
    on = set(req.filters)
    cat = _catalogue()
    # Shortlist by embedding similarity; the keyword matcher stays as fallback.
    sims, emb = _shortlist(need, cat, FAST_EMBED_BUDGET_S if fast else None)
    t = lap("embed", t)
    results = _from_catalogue(cat, need, proposed_titles, req.branch, sims)
    t = lap("score", t)
    if not fast and engine == "llm":
        results += _from_proposals(proposed, results, req.branch)
        t = lap("proposals", t)
    # Live mode, deep only: widen with catalogue pages so the list grows like a library, not a shortlist.
    if not fast and not config.effective_demo():
        have = {r.title.lower() for r in results}
        page = max(0, req.offset // max(1, req.limit))
        for r in _catalogue_search(need, req.branch, page, 20):
            if r.title.lower() not in have:
                results.append(r)
                have.add(r.title.lower())
        t = lap("search", t)
    results.sort(key=lambda r: (-r.fit, r.level, r.hours))
    chips = build_chips(need, results[:12], req.branch, on)
    filtered = apply_filters(results, chips)
    total = len(filtered)
    offset = max(0, req.offset)
    limit = max(1, min(50, req.limit))
    page_items = filtered[offset : offset + limit]
    lap("total", t0)
    log.info("discover %s engine=%s embed=%s results=%d %s", req.mode, engine, emb, total,
             " ".join(f"{k}={v:.0f}ms" for k, v in timings.items()))
    return DiscoverResponse(need=need, chips=chips, results=page_items, engine=engine, total=total, offset=offset, limit=limit,
                            has_more=offset + limit < total, deep=deep_offer() if fast else None, timings_ms=timings)


def to_json(resp: DiscoverResponse) -> str:
    return json.dumps(resp.model_dump())


# ------------------------------------------------------------------ neighbours
def _shared(a: dict, b: dict) -> list[str]:
    """Readable concepts/subjects two catalogue entries have in common."""
    short = lambda xs: [x for x in xs if len(x.split()) <= 3 and not _JUNK_SUBJECT.search(x)]  # noqa: E731 - catalogue subject strings are noisy
    la = {x.lower(): x for x in short(a["subjects"] + a["concepts"])}
    lb = {x.lower() for x in short(b["subjects"] + b["concepts"])}
    return [la[k] for k in la if k in lb]


class Neighbour(BaseModel):
    id: str
    reason: str


class Neighbours(BaseModel):
    picks: list[Neighbour]


NEIGHBOURS_SYSTEM = (
    "You are a public-library readers' advisor. A reader liked BOOK. From CANDIDATES pick the 3 they would "
    "most enjoy next. Only pick books on the same subject or a clearly shared idea; return fewer than 3 if "
    "nothing else fits. reason: one plain sentence, at most 16 words, naming the shared idea or why it "
    "follows naturally. Use only ids from CANDIDATES."
)
SIMILAR_DIR = config.CACHE_DIR / "similar"


def _llm_neighbours(me: dict, cands: list[dict], k: int) -> Optional[list[tuple[dict, str]]]:
    """Model picks + reasons among verified candidates; cached on disk. None when unavailable."""
    import hashlib

    key = hashlib.sha1((me["id"] + "|" + ",".join(c["id"] for c in cands)).encode()).hexdigest()[:16]
    path = SIMILAR_DIR / f"{key}.json"
    by_id = {c["id"]: c for c in cands}
    if path.exists():
        picks = Neighbours.model_validate_json(path.read_text()).picks
    else:
        if not config.llm_enabled():
            return None
        user = json.dumps({
            "BOOK": {"title": me["title"], "author": me["author"], "about": me["subjects"][:5] + me["concepts"][:4]},
            "CANDIDATES": [{"id": c["id"], "title": c["title"], "author": c["author"], "about": c["subjects"][:4] + c["concepts"][:3]} for c in cands],
        }, ensure_ascii=False)
        r = llm.structured(Neighbours, NEIGHBOURS_SYSTEM, user)
        if r is None:
            return None
        SIMILAR_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(r.model_dump_json())
        picks = r.picks
    out = [(by_id[p.id], p.reason.strip()) for p in picks if p.id in by_id]   # never a book outside the verified shortlist
    return out[:k] or None


def topic_text(e: dict) -> str:
    """What a book is about (no readiness prose), for book-to-book neighbours."""
    return f"{e['title']}. {e['category']}. {', '.join(e['subjects'])}. {', '.join(e['concepts'])}"


def similar(book_id: str, branch: Optional[str] = None, k: int = 3) -> list[dict]:
    """'Because you liked...' - k catalogue-verified neighbours of a book, each with a one-line reason.
    Embedding similarity when the local model is up, shared subjects/concepts otherwise. Never the book's own line."""
    cat = _catalogue()
    me = next((e for e in cat if e["id"] == book_id), None) or next((e for e in cat if e["line_id"] == book_id and e["is_target"]), None)
    if me is None:
        return []
    pool = [e for e in cat if e["id"] != me["id"] and e["line_id"] != me["line_id"]]
    ranked = embeddings.rank(topic_text(me), [(e["id"], topic_text(e)) for e in pool], top_k=len(pool), query_prefix="search_document: ")
    by_id = {e["id"]: e for e in pool}
    if ranked is not None:
        boosted = [(by_id[i], sim + 0.08 * len(_shared(me, by_id[i])) + (0.1 if by_id[i]["category"] == me["category"] else 0)) for i, sim in ranked]
        boosted.sort(key=lambda x: -x[1])
        # Prefer neighbours that share a category or subject, or are clearly similar; fill from the rest.
        # Neighbours must share the subject (same category or a shared topic); only when there
        # are too few do clearly similar books (centred cosine >= 0.3) fill in. Never pad with
        # unrelated books just to show three.
        related = [(e, v) for e, v in boosted if e["category"] == me["category"] or _shared(me, e)]
        if len(related) < k:
            related += [(e, v) for e, v in boosted if (e, v) not in related and v >= 0.3]
        shortlist = related[:10]
        if not shortlist:
            return []
        chosen = _llm_neighbours(me, [e for e, _ in shortlist], k)
        sims = dict((e["id"], sim) for e, sim in shortlist)
        picks = [(e, sims[e["id"]]) for e, _ in chosen] if chosen else shortlist[:k]
        reasons = {e["id"]: r for e, r in (chosen or [])}
    else:
        scored = sorted(((len(_shared(me, e)), e) for e in pool), key=lambda x: -x[0])  # keyword fallback
        picks = [(e, float(n)) for n, e in scored[:k] if n > 0]
        reasons = {}
    out = []
    for e, sim in picks:
        shared = _shared(me, e)
        if e["id"] in reasons:
            reason = re.sub(r"[*_`#]+", "", reasons[e["id"]]).strip()
        elif shared:
            reason = f"Also about {', '.join(shared[:2]).lower()}."
        elif e["category"] == me["category"]:
            reason = f"More {e['category'].lower()}, from another angle."
        else:
            reason = "Covers nearby ground."
        if e["level"] < me["level"]:
            reason += " A gentler read."
        elif e["level"] > me["level"]:
            reason += " A step up."
        status, _ = status_for(e, branch)
        line = next((x for x in seeds() if (x.get("isbn") or x.get("id")) == e["line_id"]), {})
        out.append({
            "id": e["id"], "title": e["title"], "author": e["author"], "reason": reason, "level": e["level"], "hours": e["hours"],
            "status": status, "line_id": e["line_id"], "line_title": line.get("title", e["title"]), "line_author": line.get("author", e["author"]),
            "is_target": e["is_target"], "similarity": round(sim, 3),
        })
    return out
