"""Guided chat endpoint. The client sends the whole turn state each time; the
state machine in `services.chat` decides the next step, so the server keeps no session."""
from __future__ import annotations

from fastapi import APIRouter

from ..services.chat import ChatReply, ChatTurn, step

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat", response_model=ChatReply)
def chat(turn: ChatTurn):
    return step(turn)
