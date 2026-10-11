"""Build a reading line for a target book.

    propose (LLM or seed)  ->  verify (catalogue)  ->  score readiness
    ->  judge pairs (LLM or heuristic)  ->  enforce rules in code  ->  route

The rules are code, not prompt text, so a confident-sounding model cannot put a
harder book before an easier one or pad the line with the same author.

Layer: services. Called by api/routes_paths.py (/api/route) and scripts/precompute.py;
uses ai.llm for proposals, readiness and judgments, integrations.catalog to verify
every title, integrations.availability for shelf status. Also owns the route cache
(data/cache/routes/*.json + index.json) and the seed targets (data/targets.json).
"""
from __future__ import annotations

import json
import re
import logging
from datetime import datetime, timezone
from typing import Optional

from ..core import config
from ..ai import llm
from ..integrations.availability import get_availability, get_demand
from ..integrations.catalog import resolve
from ..core.models import Book, CandidateList, Judgment, Readiness, Route, Stop

log = logging.getLogger("prereads.engine")

MIN_CONFIDENCE = 0.6
MAX_BEFORE = 3
MAX_AFTER = 3


# ------------------------------------------------------------------ readiness
def heuristic_readiness(book: Book, seed: Optional[dict] = None) -> Readiness:
    """Readiness without a model: the librarian's seed level when there is one, else
    keywords in the title/subjects plus page count (~35 pages an hour)."""
    if seed and seed.get("level"):
        return Readiness(
            level=int(seed["level"]),
            hours=float(seed.get("hours") or max(2.0, (book.pages or 280) / 35)),
            assumed_concepts=seed.get("concepts", []),
            style_tags=seed.get("style", []),
            one_line=seed.get("one_line", ""),
        )
    pages = book.pages or 280
    text = " ".join([book.title] + book.subjects).lower()
    level = 3
    if any(k in text for k in ("introduction", "guide", "short", "primer", "beginner", "for people in a hurry")):
        level = 2
    if any(k in text for k in ("treatise", "principia", "analysis", "theory", "advanced", "handbook")):
        level = 4
    if pages > 600:
        level = min(5, level + 1)
    return Readiness(level=level, hours=round(max(2.0, pages / 35), 1), assumed_concepts=[], style_tags=[], one_line="")


def score_readiness(book: Book, seed: Optional[dict] = None) -> tuple[Readiness, str]:
    """(readiness, engine) where engine is "llm" or "heuristic" (model off or no answer)."""
    if config.llm_enabled():
        r = llm.readiness(book)
        if r:
            if seed and not r.one_line:
                r.one_line = seed.get("one_line", "")
            return r, "llm"
    return heuristic_readiness(book, seed), "heuristic"


# ------------------------------------------------------------------ candidates
def _by_similarity(target: Book, items: list[dict]) -> list[dict]:
    """Order model proposals by embedding similarity to the target, so the verify/judge budget
    (first 8 before, 6 after) goes to the most related books. No-op when embeddings are down."""
    from ..ai import embeddings

    if len(items) < 2:
        return items
    q = f"{target.title}. {', '.join(target.subjects[:8])}. {target.summary[:400]}"
    ranked = embeddings.rank(q, [(str(i), f"{x.get('title', '')} by {x.get('author', '')}. {x.get('why', '')}") for i, x in enumerate(items)], top_k=len(items), query_prefix="search_document: ")
    if ranked is None:
        return items
    return [items[int(i)] for i, _ in ranked]


def propose(target: Book, seed: Optional[dict] = None) -> tuple[CandidateList, str]:
    """Unverified before/after candidates and where they came from ("llm", "seed" or "none").

    Seed picks are tagged `_seed` so resolve() may fall back to seed data for them;
    model picks get no such fallback and must verify in a catalogue."""
    def tagged(items: list[dict]) -> list[dict]:
        return [{**i, "_seed": True} for i in items]   # human-verified picks may use seed fallback

    if config.llm_enabled():
        c = llm.candidates(target)
        if c and (c.before or c.after):
            c.before, c.after = _by_similarity(target, c.before), _by_similarity(target, c.after)
            # Librarian seed picks first; LLM picks must verify in a catalogue or be dropped.
            if seed:
                c.before = tagged(seed.get("before", [])) + c.before
                c.after = tagged(seed.get("after", [])) + c.after
            return c, "llm"
    if seed:
        return CandidateList(before=tagged(seed.get("before", [])), after=tagged(seed.get("after", []))), "seed"
    return CandidateList(before=[], after=[]), "none"


# -------------------------------------------------------------------- judging
def heuristic_judgment(a: Readiness, b: Readiness, why: str) -> Judgment:
    if a.level < b.level:
        return Judgment(relation="prepares_for", confidence=0.7 + 0.1 * min(2, b.level - a.level), reason=why or "A gentler take on the same ideas.")
    if a.level == b.level:
        return Judgment(relation="same_level", confidence=0.6, reason=why or "About the same difficulty; read it in either order.")
    return Judgment(relation="follows", confidence=0.7, reason=why or "Goes deeper than your book.")


def judge_pair(a: Book, b: Book, ra: Readiness, rb: Readiness, why: str) -> tuple[Judgment, str]:
    """How book a relates to book b (a prepares_for b, ...); model first, else by readiness level."""
    if config.llm_enabled():
        j = llm.judge(a, b, ra, rb)
        if j:
            return j, "llm"
    return heuristic_judgment(ra, rb, why), "heuristic"


# ---------------------------------------------------------------------- rules
def _title_key(title: str) -> str:
    """Editions share a title; compare on the main title, lower-cased, without punctuation."""
    main = re.split(r"[:(]", title or "", maxsplit=1)[0]
    return re.sub(r"[^a-z0-9]+", " ", main.lower()).strip()


def _dedupe_author(stops: list[Stop]) -> list[Stop]:
    """First stop per author wins (callers sort best-first). Key is the surname part of "Surname, Given"."""
    seen: set[str] = set()
    out: list[Stop] = []
    for s in stops:
        key = (s.book.author or s.book.title).lower().split(",")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _spread(ramp: list[Stop], k: int) -> list[Stop]:
    """Trim an easiest-first ramp to k stops without losing the on-ramp: keep the easiest,
    the one closest to the target, and fill the middle evenly (stable, easiest first)."""
    if len(ramp) <= k:
        return ramp
    if k == 1:
        return [ramp[-1]]   # one slot: the stop nearest the target is the most useful
    # k evenly spaced indexes from 0 to len-1; both ends are always included.
    idx = sorted({round(i * (len(ramp) - 1) / (k - 1)) for i in range(k)})
    return [ramp[i] for i in idx]


def apply_rules(target: Stop, before: list[Stop], after: list[Stop], notes: list[str]) -> tuple[list[Stop], list[Stop]]:
    """Enforce the path rules in code (never in prompts) and return (before, after).

    Every drop is explained in `notes` as a reader sentence (shown under "Why some books were
    left off", and saved on the route for eval); the numbers behind it go to the log."""
    t = target.readiness.level
    kept_before = []
    for s in before:
        # Rule: a PreRead must be strictly easier than the target, whatever the model said.
        if s.readiness.level >= t:
            notes.append(f"Left off: {s.book.title} is not easier than your book.")
            continue
        if s.confidence < MIN_CONFIDENCE:
            notes.append(f"Left off: {s.book.title} was not a clear enough fit to read first.")
            log.info("dropped %r: confidence %.2f < %s", s.book.title, s.confidence, MIN_CONFIDENCE)
            continue
        if s.book.id == target.book.id:
            continue
        kept_before.append(s)
    # Rule: one book per author on the before-line. Sorting easiest-first, then most confident,
    # means the author's gentlest, best-judged book is the one that stays.
    kept_before = _dedupe_author(sorted(kept_before, key=lambda s: (s.readiness.level, -s.confidence)))
    # Easiest-first ramp. kept_before is already sorted by level, so today this keeps every stop;
    # it guards the order _spread relies on.
    ramp: list[Stop] = []
    for s in kept_before:
        if not ramp or s.readiness.level >= ramp[-1].readiness.level:
            ramp.append(s)
    # Rule: at most MAX_BEFORE. _spread (not [:3]) so a long ramp keeps its easiest on-ramp.
    kept_before = _spread(ramp, MAX_BEFORE)

    # Rule: a book can't be both before and after; the before-stop wins. Match on id and on
    # main title, because two editions of one book have different ids.
    kept_after = []
    before_ids = {s.book.id for s in kept_before} | {_title_key(s.book.title) for s in kept_before}
    seen_after: set[str] = set()
    for s in after:
        if s.book.id in before_ids or _title_key(s.book.title) in before_ids:
            notes.append(f"Left off the next reads: {s.book.title} is already one of your PreReads.")
            continue
        # One level easier is fine for a follow-on (a lighter companion); two or more is a step back.
        if s.readiness.level < t - 1:
            notes.append(f"Left off the next reads: {s.book.title} is much easier than your book.")
            continue
        if s.confidence < MIN_CONFIDENCE or s.book.id == target.book.id or _title_key(s.book.title) in seen_after:
            continue
        seen_after.add(_title_key(s.book.title))
        kept_after.append(s)
    # An author's own follow-on is a natural next stop, so no author de-dupe here.
    kept_after = sorted(kept_after, key=lambda s: (s.readiness.level, -s.confidence))[:MAX_AFTER]
    return kept_before, kept_after


# ---------------------------------------------------------------------- route
def _not_before_note(title: str, relation: str) -> str:
    """Reader sentence for a candidate the judge did not place before the target."""
    if relation == "same_level":
        return f"Left off: {title} is at a similar level to your book, so it need not come first."
    if relation == "follows":
        return f"Left off: {title} goes further than your book, so it fits better after it."
    return f"Left off: {title} is not closely enough related to your book."


def _stop(role: str, book: Book, seed: Optional[dict], why: str, confidence: float) -> Stop:
    if role == "target" and seed and seed.get("level"):
        r = heuristic_readiness(book, seed)    # a librarian's curated level for a seed target outranks a model estimate
    else:
        r, _ = score_readiness(book, seed)
    availability = get_availability(book)
    return Stop(role=role, order=0, book=book, readiness=r, why=why, confidence=confidence,
                availability=availability, demand=get_demand(book, availability))


def build_route(target_seed: dict, target_book: Optional[Book] = None) -> Route:
    """Run the whole pipeline for one target and return the Route (not saved; see save_route).

    target_seed is a targets.json entry or just {title, author}; target_book skips the
    target lookup when the caller already resolved it. Raises ValueError if the target
    does not resolve in any catalogue."""
    notes: list[str] = []
    target = target_book or resolve(target_seed["title"], target_seed.get("author", ""), seed=target_seed)
    if target is None:
        raise ValueError(f"target not found in any catalogue: {target_seed['title']}")
    t_stop = _stop("target", target, target_seed, target_seed.get("one_line", "") or "The book you asked about.", 1.0)

    cands, engine = propose(target, target_seed)
    engines = {engine}

    # Budget: only the first 8 before / 6 after candidates are verified and judged
    # (each costs a catalogue lookup and up to two model calls).
    before: list[Stop] = []
    for c in cands.before[:8]:
        b = resolve(c["title"], c.get("author", ""), seed=c if c.get("_seed") else None)
        if b is None:
            notes.append(f"Left off: {c['title']} could not be found in the catalogue.")
            continue
        if b.id == target.id:
            continue
        if not b.subjects:
            b.subjects = list(target.subjects)   # same field; keeps demo call numbers sensible
        r, _ = score_readiness(b, c)
        j, je = judge_pair(b, target, r, t_stop.readiness, c.get("why", ""))
        engines.add(je)
        if c.get("_seed") and (j.relation != "prepares_for" or j.confidence < MIN_CONFIDENCE) and r.level < t_stop.readiness.level:
            # Librarian on-ramp: the model is advisory here; the readiness rules in apply_rules still decide.
            # Not a drop, so not a reader note; the model's view goes to the log only.
            log.info("model judged %r %s (%.2f); librarian pick kept", b.title, j.relation, j.confidence)
            j, je = heuristic_judgment(r, t_stop.readiness, c.get("why", "")), "seed"
        if j.relation != "prepares_for":
            notes.append(_not_before_note(b.title, j.relation))
            log.info("%r judged %s (%.2f), not placed before", b.title, j.relation, j.confidence)
            continue
        before.append(_stop("before", b, c, j.reason, j.confidence))

    after: list[Stop] = []
    for c in cands.after[:6]:
        b = resolve(c["title"], c.get("author", ""), seed=c if c.get("_seed") else None)
        if b is None or b.id == target.id:
            continue
        if not b.subjects:
            b.subjects = list(target.subjects)
        r, _ = score_readiness(b, c)
        j, je = judge_pair(target, b, t_stop.readiness, r, c.get("why", ""))
        engines.add(je)
        if j.relation == "unrelated":
            continue
        # Any related follow-on is acceptable, so confidence is floored at the MIN_CONFIDENCE cut.
        after.append(_stop("after", b, c, c.get("why", "") or j.reason, max(j.confidence, 0.6)))

    before, after = apply_rules(t_stop, before, after, notes)
    stops = before + [t_stop] + after
    for i, s in enumerate(stops):
        s.order = i
    engine_label = "llm" if "llm" in engines else ("seed" if "seed" in engines else "heuristic")
    return Route(target_id=target.id, stops=stops, generated_at=datetime.now(timezone.utc).isoformat(), engine=engine_label, notes=notes)


# ---------------------------------------------------------------------- cache
def _route_path(target_id: str):
    safe = target_id.replace("/", "_").replace(":", "_")
    return config.ROUTES_DIR / f"{safe}.json"


def save_route(route: Route) -> None:
    _route_path(route.target_id).write_text(route.model_dump_json(indent=2), encoding="utf-8")


def load_route(target_id: str) -> Optional[Route]:
    p = _route_path(target_id)
    if not p.exists():
        return None
    return Route.model_validate_json(p.read_text(encoding="utf-8"))


def load_index() -> list[dict]:
    p = config.CACHE_DIR / "index.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def save_index(entries: list[dict]) -> None:
    (config.CACHE_DIR / "index.json").write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")


def seeds() -> list[dict]:
    p = config.DATA_DIR / "targets.json"
    return json.loads(p.read_text(encoding="utf-8"))


def find_seed(target_id: str) -> Optional[dict]:
    """The targets.json entry whose isbn or id equals target_id, else None."""
    for s in seeds():
        if s.get("isbn") == target_id or s.get("id") == target_id:
            return s
    return None
