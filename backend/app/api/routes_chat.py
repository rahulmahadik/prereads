"""Guided chat endpoint. The client sends the whole turn state each time; the
state machine in `services.chat` decides the next step, so the server keeps no session."""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from ..services.chat import ChatReply, ChatTurn, astream, step

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatReply)
def chat(turn: ChatTurn):
    return step(turn)


@router.post("/chat/stream")
async def chat_stream(turn: ChatTurn):
    """Same as /api/chat, but streams each real step (NDJSON) as it starts and finishes. Async, so an
    open stream waits on the event loop instead of holding a worker thread."""
    return StreamingResponse(astream(turn), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
