"""Discovery endpoints: free-text "what do you want to read" and "Because you liked".

All the work (need parsing, shortlist, verification, scoring) is in `services.discover`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException

from ..services.discover import DiscoverRequest, DiscoverResponse, discover, similar

router = APIRouter(prefix="/api", tags=["discover"])


@router.post("/discover", response_model=DiscoverResponse)
def discover_(req: DiscoverRequest):
    if len(req.text.strip()) < 2:
        raise HTTPException(422, "Tell me a little more.")
    return discover(req)


@router.get("/similar")
def similar_(id: str, branch: Optional[str] = None):
    """'Because you liked...': three catalogue-verified neighbours with a one-line reason."""
    return {"books": similar(id, branch or None)}


@router.get("/suggestions")
def suggestions_(lang: Optional[str] = None, n: int = 4, seed: Optional[int] = None):
    """Example requests for Home's "Try:" row, generated from the catalogue (rotates daily)."""
    from ..services.suggest import suggestions

    return suggestions(lang, max(1, min(n, 8)), seed)
