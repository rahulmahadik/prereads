"""ASGI entry point (`uvicorn app.main:app`).

Builds the FastAPI app, mounts the API routers from `app.api`, starts two background
jobs (daily NLB open-data refresh, embedding warm-up) and serves the built frontend
(frontend/dist) when it exists. Endpoints themselves live in `app/api/routes_*.py`.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import anyio
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import ROUTERS
from .core import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("prereads.api")

app = FastAPI(title="PreReads", version="0.1.0")


@app.on_event("startup")
async def _more_worker_threads() -> None:
    """Blocking endpoints share one thread pool (40 by default). Most of them wait on the network or
    the model, so a few dozen readers at once could take every thread; give the pool more room."""
    anyio.to_thread.current_default_thread_limiter().total_tokens = config.SERVER_THREADS


@app.on_event("startup")
def _refresh_nlb_open_data() -> None:
    """Keep the NLB open-data snapshot fresh: on startup and then daily, re-download NLB's
    annual loans dataset from data.gov.sg (with DATAGOV_API_KEY when set) if the snapshot is
    older than a day. Runs in the background; a failure keeps the previous snapshot."""
    import datetime as dt
    import importlib.util
    import time as _time

    from .integrations import nlb_datasets as _nd

    def stale() -> bool:
        as_of = (_nd.library_stats() or {}).get("as_of")
        return not as_of or as_of < (dt.date.today() - dt.timedelta(days=1)).isoformat()

    def refresh_once() -> None:
        if config.effective_demo() or not stale():
            return
        try:
            spec = importlib.util.spec_from_file_location("fetch_nlb_datasets", config.ROOT / "scripts" / "fetch_nlb_datasets.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            mod.build_stats(dt.date.today().isoformat())
            # nlb_datasets.load() re-reads a file when its mtime changes, so no cache to clear.
            logging.getLogger("prereads").info("NLB open data refreshed from data.gov.sg")
        except Exception as exc:  # noqa: BLE001 - keep serving the previous snapshot
            logging.getLogger("prereads").warning("NLB open data refresh failed: %s", exc)

    def loop() -> None:
        while True:
            refresh_once()
            _time.sleep(24 * 3600)

    threading.Thread(target=loop, daemon=True, name="nlb-open-data").start()


@app.on_event("startup")
def _warm_embeddings() -> None:
    """Embed the catalogue in the background so the first discovery request is fast."""
    from .ai import embeddings as _e
    from .services import discover as _d

    def run():
        try:
            _e.warm([_d.entry_text(x) for x in _d._catalogue()] + [_d.topic_text(x) for x in _d._catalogue()])
        except Exception:  # noqa: BLE001  best effort: discovery still works, just slower on first call
            pass

    threading.Thread(target=run, daemon=True).start()


app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_visit_lock = threading.Lock()


@app.middleware("http")
async def visit_log(request: Request, call_next):
    """Append one JSON line per request to VISIT_LOG (off when unset). Static assets and health
    checks are skipped; the visitor IP is Cloudflare's CF-Connecting-IP when present."""
    response = await call_next(request)
    path = request.url.path
    if config.VISIT_LOG and not path.startswith(("/assets/", "/api/health")):
        rec = {
            "t": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ip": request.headers.get("cf-connecting-ip") or (request.client.host if request.client else ""),
            "country": request.headers.get("cf-ipcountry", ""),
            "method": request.method,
            "path": path,
            "query": request.url.query[:200],
            "status": response.status_code,
            "ua": request.headers.get("user-agent", "")[:300],
        }
        try:
            with _visit_lock, open(config.VISIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.warning("visit log write failed: %s", exc)
    return response

for _router in ROUTERS:
    app.include_router(_router)


# Serve the built frontend if present. The catch-all is registered after the API
# routers because Starlette matches in order; registered earlier it would shadow them.
_dist = config.REPO_ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        """Static file if it exists, else index.html (the hash router takes over). Async: the page
        itself never waits behind busy worker threads when many readers are using the AI at once."""
        file = _dist / path
        if path and file.exists() and file.is_file():
            # the service worker, page shell and manifest must never be cached by the CDN,
            # or phones keep running an old app after a deploy
            fresh = path in ("sw.js", "index.html", "manifest.webmanifest")
            return FileResponse(file, headers={"Cache-Control": "no-cache"} if fresh else None)
        return FileResponse(_dist / "index.html", headers={"Cache-Control": "no-cache"})
