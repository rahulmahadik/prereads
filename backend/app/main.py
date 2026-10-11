"""ASGI entry point (`uvicorn app.main:app`).

Builds the FastAPI app, mounts the API routers from `app.api`, warms the embedding
cache in the background, and serves the built frontend (frontend/dist) when it exists.
Endpoints themselves live in `app/api/routes_*.py`.
"""
from __future__ import annotations

import logging
import threading

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import ROUTERS
from .core import config

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("prereads.api")

app = FastAPI(title="PreReads", version="0.1.0")


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

for _router in ROUTERS:
    app.include_router(_router)


# Serve the built frontend if present. The catch-all is registered after the API
# routers because Starlette matches in order; registered earlier it would shadow them.
_dist = config.REPO_ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        """Static file if it exists, else index.html (the hash router takes over)."""
        file = _dist / path
        if path and file.exists() and file.is_file():
            return FileResponse(file)
        return FileResponse(_dist / "index.html")
