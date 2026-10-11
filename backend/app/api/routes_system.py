"""System endpoints: health check and the runtime mode switch.

`/api/mode` lets the Settings sheet turn demo data, the AI provider and live NLB
calls on and off without a restart. The overrides live in `core.config.RUNTIME`.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..core import config
from ..services.engine import load_index

router = APIRouter(prefix="/api", tags=["system"])


class ModeRequest(BaseModel):
    demo: Optional[bool] = None
    use_llm: Optional[bool] = None
    use_nlb: Optional[bool] = None


@router.get("/health")
def health():
    return {"ok": True, "mode": config.mode(), "cached_routes": len(load_index())}


@router.get("/mode")
def get_mode():
    return {**config.mode_info(), "cached_routes": len(load_index())}


@router.post("/mode")
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
