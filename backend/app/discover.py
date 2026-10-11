"""Discovery: a reader's sentence in, ranked and filterable recommendations out.

    "I want to understand investing but I only have two weeks"
    -> Need{topics:[investing], max_hours:10, level:1, ...}
    -> candidates (LLM-proposed, catalogue-verified) + cached targets that match
    -> scored for fit (topic, level, time, availability at the reader's branch)
    -> filter chips generated from the need and the result set

With OPENAI_API_KEY the need and the candidate list come from the model. Without
it, a heuristic parser handles the common phrasings so the demo still feels
intelligent, and the recommendations are drawn from the precomputed catalogue.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Literal, Optional

from pydantic import BaseModel, Field

from . import config, embeddings, llm
from .availability import BRANCHES, get_availability, get_demand
from .catalog import nlb, openlibrary_search_many, resolve
from .engine import heuristic_readiness
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


class DiscoverRequest(BaseModel):
    text: str
    branch: Optional[str] = None
    filters: list[str] = Field(default_factory=list)   # chip ids that are on
    offset: int = 0
    limit: int = 10


class DiscoverResponse(BaseModel):
    need: Need
    chips: list[FilterChip]
    results: list[Recommendation]
    engine: str
    total: int = 0
    offset: int = 0
    limit: int = 10
    has_more: bool = False


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


def propose(text: str) -> tuple[Need, list[Proposed], str]:
    if config.llm_enabled():
        p = llm.structured(Proposal, PROPOSE_SYSTEM, text, temperature=llm.TEMP_PROPOSE)
        if p:
            if not p.need.summary:
                p.need.summary = text.strip()
            return p.need, p.books, "llm"
    return heuristic_need(text), [], "heuristic"


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
            bits.append(f"a step up — we'll show {entry['before_count']} books to read first")
        if need.max_hours and entry["hours"] <= need.max_hours:
            bits.append(f"fits your {round(need.max_hours)} h")
        if branch and branch_fit == 1.0:
            bits.append(f"on the shelf at {BRANCHES.get(branch, branch).replace(' Public Library', '').replace(' Regional Library', '').replace(' Library', '')}")
        why = (entry["one_line"] or "A strong match for what you asked.") + (" " + ", ".join(bits).capitalize() + "." if bits else "")
    return round(fit, 3), why


def status_for(entry: dict, branch: Optional[str]) -> tuple[str, list[str]]:
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
    return chips


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
        # age/language: the demo catalogue is adult English; keep results and let the UI say so
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
    for i, b in enumerate(books):
        rd = heuristic_readiness(b)
        av = get_availability(b)
        dm = get_demand(b, av)
        status, names = status_for({"availability": av}, branch)
        level_fit = 1.0 if not need.level else (1.0 if rd.level <= need.level else max(0.2, 1 - 0.3 * (rd.level - need.level)))
        time_fit = 1.0 if not need.max_hours else (1.0 if rd.hours <= need.max_hours else max(0.2, need.max_hours / rd.hours))
        fit = round(0.55 * (1 - i / max(1, len(books) * 2)) + 0.25 * level_fit + 0.2 * time_fit, 3)
        out.append(Recommendation(
            id=b.id, line_id=b.id, is_target=True, title=b.title, author=b.author, category=(b.subjects or ["Catalogue"])[0],
            level=rd.level, hours=rd.hours, why=(b.summary[:160] + "…") if b.summary else "From the catalogue search for your topic.",
            fit=min(0.89, fit), status=status, available_at=names,
            hot_at=[h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in dm.hot_branches], before_count=0,
        ))
    return out


# ------------------------------------------------------------------ entry
def discover(req: DiscoverRequest) -> DiscoverResponse:
    need, proposed, engine = propose(req.text)
    proposed_titles = {p.title.lower(): p.why for p in proposed}
    on = set(req.filters)
    results: list[Recommendation] = []
    cat = _catalogue()
    # Shortlist by embedding similarity (local nomic-embed-text); the keyword matcher stays as fallback.
    sims: dict[str, float] = {}
    ranked = embeddings.rank(" ".join([need.summary] + need.topics), [(e["id"], entry_text(e)) for e in cat], top_k=40)
    if ranked is not None:
        sims = dict(ranked)
    for e in cat:
        fit, why = score(e, need, proposed_titles, req.branch, semantic_topic(sims.get(e["id"], 0.0)))
        if fit <= 0:
            continue
        status, names = status_for(e, req.branch)
        results.append(Recommendation(
            id=e["id"], line_id=e["line_id"], is_target=e["is_target"], title=e["title"], author=e["author"], category=e["category"], level=e["level"], hours=e["hours"],
            why=why, fit=fit, status=status, available_at=names, hot_at=[h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in e["hot"]],
            before_count=e["before_count"],
        ))
    # Live mode: books the model proposed that are not on any cached line are
    # verified in the catalogue and added (their line is built when opened).
    if engine == "llm":
        have = {r.title.lower() for r in results}
        for i, pr in enumerate(proposed[:8]):
            if pr.title.lower() in have:
                continue
            b = resolve(pr.title, pr.author)
            if b is None:
                continue
            rd, _ = score_readiness(b)
            av = get_availability(b)
            dm = get_demand(b, av)
            entry = {"availability": av}
            status, names = status_for(entry, req.branch)
            results.append(Recommendation(
                id=b.id, line_id=b.id, is_target=True, title=b.title, author=b.author,
                category=(b.subjects or ["Suggested"])[0], level=rd.level, hours=rd.hours, why=pr.why,
                fit=round(max(0.5, 0.95 - 0.04 * i), 3), status=status, available_at=names,
                hot_at=[h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in dm.hot_branches],
                before_count=0,
            ))
            have.add(b.title.lower())
    # Live mode: widen with catalogue pages so the list grows like a library, not a shortlist.
    if not config.effective_demo():
        have = {r.title.lower() for r in results}
        page = max(0, req.offset // max(1, req.limit))
        for r in _catalogue_search(need, req.branch, page, 20):
            if r.title.lower() not in have:
                results.append(r)
                have.add(r.title.lower())
    results.sort(key=lambda r: (-r.fit, r.level, r.hours))
    chips = build_chips(need, results[:12], req.branch, on)
    filtered = apply_filters(results, chips)
    total = len(filtered)
    offset = max(0, req.offset)
    limit = max(1, min(50, req.limit))
    page_items = filtered[offset : offset + limit]
    return DiscoverResponse(need=need, chips=chips, results=page_items, engine=engine, total=total, offset=offset, limit=limit, has_more=offset + limit < total)


def to_json(resp: DiscoverResponse) -> str:
    return json.dumps(resp.model_dump())


# ------------------------------------------------------------------ neighbours
def _shared(a: dict, b: dict) -> list[str]:
    """Readable concepts/subjects two catalogue entries have in common."""
    short = lambda xs: [x for x in xs if len(x.split()) <= 3]  # noqa: E731 - catalogue subject strings can be noisy
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
    "most enjoy next. reason: one plain sentence, at most 16 words, naming the shared idea or why it follows "
    "naturally. Use only ids from CANDIDATES."
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
        related = [(e, v) for e, v in boosted if e["category"] == me["category"] or _shared(me, e) or v >= 0.2]
        shortlist = (related + [x for x in boosted if x not in related])[:10]
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
            reason = reasons[e["id"]]
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
