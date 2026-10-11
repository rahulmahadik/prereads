from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, llm
from .ask import answer
from .availability import BRANCHES
from .catalog import nlb, NLBClient, openlibrary_search_many, resolve
from .engine import build_route, find_seed, load_index, load_route, save_index, save_route, seeds
from .chat import ChatReply, ChatTurn, books_for, browse, step
from .discover import DiscoverRequest, DiscoverResponse, discover
from . import stt
from .tts import synthesize
from .models import AskRequest, AskResponse, Route, ScanResult

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("prereads.api")

app = FastAPI(title="PreReads", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
def health():
    return {"ok": True, "mode": config.mode(), "cached_routes": len(load_index())}


class ModeRequest(BaseModel):
    demo: Optional[bool] = None
    use_llm: Optional[bool] = None
    use_nlb: Optional[bool] = None


@app.get("/api/mode")
def get_mode():
    return {**config.mode_info(), "cached_routes": len(load_index())}


@app.post("/api/mode")
def set_mode(req: ModeRequest):
    """Flip between demo data and real calls at runtime (no restart). Keys still
    come from .env; a toggle that needs a missing key simply stays off."""
    if req.demo is not None:
        config.RUNTIME["demo"] = req.demo
    if req.use_llm is not None:
        config.RUNTIME["use_llm"] = req.use_llm
    if req.use_nlb is not None:
        config.RUNTIME["use_nlb"] = req.use_nlb
    return {**config.mode_info(), "cached_routes": len(load_index())}


@app.get("/api/resolve")
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
    page = merged[offset : offset + limit] if config.effective_demo() else (hits[offset : offset + limit] + [l for l in live if l["id"] not in seen])[:limit]
    total = len(merged)
    return {"results": page, "total": total, "offset": offset, "limit": limit, "has_more": offset + limit < total}


@app.get("/api/route", response_model=Route)
def route(id: str, title: Optional[str] = None, author: Optional[str] = None, refresh: bool = False):
    if not refresh:
        cached = load_route(id)
        if cached:
            return cached
    if config.effective_demo():
        raise HTTPException(404, "Not in the demo cache. Run scripts/precompute.py or pick a cached title.")
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


@app.post("/api/scan", response_model=ScanResult)
async def scan(image: UploadFile = File(...)):
    if not config.llm_enabled():
        raise HTTPException(503, "Scanning needs a vision model (Ollama not reachable, or demo mode is on). Type the title instead.")
    data = await image.read()
    if len(data) > 8_000_000:
        raise HTTPException(413, "Image too large; keep it under 8 MB.")
    res = llm.scan(data, image.content_type or "image/jpeg")
    if res is None or not res.title:
        raise HTTPException(422, "Could not read a book in that photo. Try the cover, closer, with more light.")
    return res


@app.post("/api/ask", response_model=AskResponse)
def ask(req: AskRequest):
    r = load_route(req.target_id)
    if r is None:
        raise HTTPException(404, "Build the reading path first.")
    return answer(r, req)


@app.get("/api/browse")
def browse_(by: str = "category", ids: Optional[str] = None):
    """by=author|category -> groups; ids=a,b,c -> the books in a group."""
    if ids:
        return {"books": books_for(ids.split(","))}
    return {"groups": browse("author" if by == "author" else "category")}


@app.post("/api/discover", response_model=DiscoverResponse)
def discover_(req: DiscoverRequest):
    if len(req.text.strip()) < 2:
        raise HTTPException(422, "Tell me a little more.")
    return discover(req)


class TtsRequest(BaseModel):
    text: str
    voice: Optional[str] = None
    lang: Optional[str] = None


@app.post("/api/tts")
def tts(req: TtsRequest):
    """Natural voice for any text on screen. 503 when no key -> browser voice fallback."""
    if not config.llm_enabled():
        raise HTTPException(503, "Natural voice is not available; using the browser voice instead.")
    audio = synthesize(req.text, req.voice, req.lang)
    if audio is None:
        raise HTTPException(502, "Voice synthesis failed; using the browser voice instead.")
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "public, max-age=86400"})


@app.post("/api/stt")
async def stt_(audio: UploadFile = File(...), lang: str = "en"):
    """Local speech-to-text (faster-whisper). 503 -> the browser's SpeechRecognition takes over."""
    if not stt.available():
        raise HTTPException(503, "Local speech recognition is not installed; using the browser's.")
    data = await audio.read()
    if len(data) > 12_000_000:
        raise HTTPException(413, "Recording too long.")
    text = stt.transcribe(data, lang[:2] or "en")
    if text is None:
        raise HTTPException(422, "Didn't catch that.")
    return {"text": text, "engine": f"faster-whisper {stt.STT_MODEL}"}


@app.post("/api/chat", response_model=ChatReply)
def chat(turn: ChatTurn):
    return step(turn)


@app.get("/api/branches")
def branches():
    return {"branches": [{"code": c, "name": n} for c, n in BRANCHES.items()]}


@app.get("/api/targets")
def targets():
    return {"targets": [{"id": s.get("isbn") or s.get("id"), "title": s["title"], "author": s.get("author", ""), "unfinished": bool(s.get("unfinished"))} for s in seeds()]}


@app.get("/api/popular")
def popular(limit: int = 12):
    """Books in demand right now, from the demand signals on cached lines
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
        score = 3 * len(t.demand.hot_branches) + 2 * t.demand.reservations + 2 * (out / total)
        rows.append({
            "id": sid, "title": t.book.title, "author": t.book.author, "category": (s.get("subjects") or ["Other"])[0],
            "hot_at": [h.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "") for h in t.demand.hot_branches],
            "queue": t.demand.reservations, "score": round(score, 2), "demo": t.demand.demo,
        })
    rows.sort(key=lambda x: (-x["score"], x["title"]))
    return {"popular": rows[:limit]}


# Serve the built frontend if present (python -m uvicorn app.main:app --port 8000)
_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        file = _dist / path
        if path and file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(_dist / "index.html")
