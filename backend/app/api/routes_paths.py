"""Reading-path endpoints: title search, the path itself, seed targets, popular
books, browse groups and grounded questions about a path.

Handlers stay thin: the path is built in `services.engine`, questions are answered
in `services.ask`, and every title shown has come back from a catalogue lookup.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from ..core import config
from ..core.models import AskRequest, AskResponse, Route
from ..integrations.catalog import NLBClient, nlb, openlibrary_search_many, resolve
from ..services.ask import answer
from ..services.chat import books_for, browse
from ..services.engine import build_route, find_seed, load_index, load_route, save_index, save_route, seeds

router = APIRouter(prefix="/api", tags=["paths"])


@router.get("/resolve")
def resolve_q(q: str = Query(min_length=2), offset: int = 0, limit: int = 8):
    """Title search, paged: cached targets first (instant), then the live catalogue."""
    ql = q.lower().strip()
    hits = [e for e in load_index() if ql in e["title"].lower() or ql in e.get("author", "").lower()]
    hits = sorted(hits, key=lambda e: (not e["title"].lower().startswith(ql), e["title"]))
    live: list[dict] = []
    if not config.effective_demo():
        if nlb().enabled():
            data = nlb()._get("GetTitles", Keywords=q, Limit=limit, Offset=offset)
            for it in (data or {}).get("titles", []) or []:
                b = NLBClient.to_book(it)
                live.append({"id": b.id, "title": b.title, "author": b.author, "cached": False})
        else:
            for b in openlibrary_search_many(q, page=offset // max(1, limit) + 1, size=limit):
                live.append({"id": b.id, "title": b.title, "author": b.author, "cached": False})
    seen = {h["id"] for h in hits}
    merged = hits + [l for l in live if l["id"] not in seen]
    # Demo pages through the cached list; live mode re-queries the catalogue per page,
    # so only the cached hits are sliced and the live page is appended after them.
    page = merged[offset : offset + limit] if config.effective_demo() else (hits[offset : offset + limit] + [l for l in live if l["id"] not in seen])[:limit]
    total = len(merged)
    return {"results": page, "total": total, "offset": offset, "limit": limit, "has_more": offset + limit < total}


@router.get("/route", response_model=Route)
def route(id: str, title: Optional[str] = None, author: Optional[str] = None, refresh: bool = False):
    """The reading path for one target: cache first, else build it live and cache it.

    A target that is not a seed must come with a title so the catalogue can verify it."""
    if not refresh:
        cached = load_route(id)
        if cached:
            return cached
    if config.effective_demo():
        raise HTTPException(404, "No reading path for this title yet. Pick one from the list.")
    seed = find_seed(id)
    if seed is None:
        # Unknown title: it must verify in a catalogue; no seed fallback.
        if not title:
            raise HTTPException(404, "Title not found. Search first so the catalogue can verify it.")
        target = resolve(title, author or "")
        if target is None:
            raise HTTPException(404, f"'{title}' is not in the catalogue.")
        seed = {"title": target.title, "author": target.author}
        r = build_route(seed, target_book=target)
    else:
        r = build_route(seed)
    save_route(r)
    idx = load_index()
    if r.target_id not in {e["id"] for e in idx}:
        t = next(s for s in r.stops if s.role == "target")
        idx.append({"id": r.target_id, "title": t.book.title, "author": t.book.author, "cached": True})
        save_index(idx)
    return r


@router.post("/ask", response_model=AskResponse)
def ask(req: AskRequest):
    r = load_route(req.target_id)
    if r is None:
        raise HTTPException(404, "Build the reading path first.")
    return answer(r, req)


@router.get("/browse")
def browse_(by: str = "category", ids: Optional[str] = None):
    """by=author|category -> groups; ids=a,b,c -> the books in a group."""
    if ids:
        books = books_for(ids.split(","))
        return {"books": [{**b, "cover_url": b.get("cover_url") or _cover_of(b["id"])} for b in books]}
    return {"groups": browse("author" if by == "author" else "category")}


def _cover_of(target_id: str) -> Optional[str]:
    """The cached path's target cover (None when there is no cached path or no cover)."""
    r = load_route(target_id)
    t = next((x for x in r.stops if x.role == "target"), None) if r else None
    return t.book.cover_url if t else None


@router.get("/targets")
def targets():
    return {"targets": [{"id": s.get("isbn") or s.get("id"), "title": s["title"], "author": s.get("author", ""), "unfinished": bool(s.get("unfinished")), "cover_url": _cover_of(s.get("isbn") or s.get("id"))} for s in seeds()]}


@router.get("/popular")
def popular(limit: int = 12):
    """Books in demand right now, from the demand signals on cached reading paths
    (checkout-trend hot branches, reservation queues, how few copies are in)."""
    rows = []
    for s in seeds():
        sid = s.get("isbn") or s.get("id")
        r = load_route(sid)
        if not r:
            continue
        t = next(x for x in r.stops if x.role == "target")
        av = t.availability
        total = sum(a.total for a in av) or 1
        out = sum(a.total - a.available for a in av)
        # Weights: a trending branch counts most, then each reservation, then the share on loan.
        score = 3 * len(t.demand.hot_branches) + 2 * t.demand.reservations + 2 * (out / total)
        rows.append({
            "id": sid, "title": t.book.title, "author": t.book.author, "cover_url": t.book.cover_url, "category": (s.get("subjects") or ["Other"])[0],
            "hot_at": [h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in t.demand.hot_branches],
            "queue": t.demand.reservations, "score": round(score, 2), "demo": t.demand.demo,
        })
    rows.sort(key=lambda x: (-x["score"], x["title"]))
    rows = rows[:limit]
    # Per-title demand is live only from the NLB API (checkout trends); no open dataset has
    # per-title loans, so without the API the rows stay demo. The dataset adds an honest
    # all-of-NLB aggregate (loans, digital use) for the year it covers.
    from ..integrations import nlb_datasets

    src = nlb_datasets.source()
    live = bool(rows) and src == "api" and not any(r["demo"] for r in rows)
    source = "api" if live else "demo"
    for r in rows:
        r["source"] = source
    facts = nlb_datasets.headline() if src in ("api", "dataset") else None
    return {"popular": rows, "source": source, "as_of": None, "facts": facts}
