"""Media endpoints: cover scan (vision model), speech-to-text and text-to-speech.

Each one answers 503 when its model is not available, which tells the browser
to fall back (typed title, built-in SpeechRecognition, built-in speech synthesis).
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..ai import llm, stt
from ..ai.tts import Busy as tts_busy, synthesize
from ..core import config
from ..core.guard import image_kind
from ..core.models import ScanResult

router = APIRouter(prefix="/api", tags=["media"])


class TtsRequest(BaseModel):
    text: str = Field(max_length=5000)
    voice: Optional[str] = None
    lang: Optional[str] = None


@router.post("/scan", response_model=ScanResult)
async def scan(image: UploadFile = File(...)):
    """Read title/author off a cover photo. The client still resolves the result in the catalogue."""
    if not config.llm_enabled():
        raise HTTPException(503, "Scanning needs a vision model, and none is available right now. Type the title instead.")
    data = await image.read(8_000_001)
    if len(data) > 8_000_000:
        raise HTTPException(413, "Image too large; keep it under 8 MB.")
    kind = image_kind(data)          # from the bytes, not the client's label: no scripts or bombs
    if kind is None:
        raise HTTPException(415, "That file isn't a photo we can read. Use a JPEG, PNG, WebP or HEIC picture of the cover.")
    if not llm.reserve():
        raise HTTPException(429, "The AI is busy with other readers; try again in a moment or type the title.")
    try:
        res = await run_in_threadpool(llm.scan, data, kind)
    finally:
        llm.release()
    if res is None or not res.title:
        raise HTTPException(422, "Could not read a book in that photo. Try the cover, closer, with more light.")
    return res


@router.post("/tts")
def tts(req: TtsRequest):
    """Natural voice for any text on screen. 503 -> browser voice fallback. 429 when every voice slot is
    taken: the page uses the browser voice for this reading but keeps trying the natural one next time."""
    try:
        out = synthesize(req.text, req.voice, req.lang)
    except tts_busy:
        raise HTTPException(429, "Natural voice is busy; using the browser voice instead.")
    if out is None:
        raise HTTPException(503, "Natural voice is not available; using the browser voice instead.")
    audio, media = out
    return Response(content=audio, media_type=media, headers={"Cache-Control": "public, max-age=86400"})


@router.post("/stt")
async def stt_(audio: UploadFile = File(...), lang: str = "en"):
    """Speech-to-text with faster-whisper. 503 -> the browser's SpeechRecognition takes over."""
    if not stt.available():
        raise HTTPException(503, "Speech recognition is not available; using the browser's.")
    data = await audio.read()
    if len(data) > 12_000_000:
        raise HTTPException(413, "Recording too long.")
    text = stt.transcribe(data, lang[:2] or "en")
    if text is None:
        raise HTTPException(422, "Didn't catch that.")
    return {"text": text, "engine": f"faster-whisper {stt.STT_MODEL}"}
