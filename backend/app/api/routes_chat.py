"""Guided chat endpoint. The client sends the whole turn state each time; the
state machine in `services.chat` decides the next step, so the server keeps no session."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..services.chat import ChatReply, ChatTurn, step, stream

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatReply)
def chat(turn: ChatTurn):
    return step(turn)


@router.post("/chat/stream")
def chat_stream(turn: ChatTurn):
    """Same as /api/chat, but streams each real step (NDJSON) as it starts and finishes."""
    return StreamingResponse(stream(turn), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
