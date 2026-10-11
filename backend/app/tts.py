"""Natural voice: text -> speech via OpenAI's TTS, cached on disk.

Falls back to nothing (503) when there is no key; the frontend then uses the
browser's built-in voices, so "Listen" always works.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

from . import config, llm

log = logging.getLogger("prereads.tts")

TTS_DIR = config.CACHE_DIR / "tts"
TTS_DIR.mkdir(parents=True, exist_ok=True)

# A warm, unhurried librarian. Kept short: the instructions field steers tone.
STYLE = (
    "Speak like a friendly public librarian in Singapore: warm, clear, unhurried, "
    "slightly conversational. Pause briefly between sentences. Pronounce book titles "
    "and author names carefully."
)


def synthesize(text: str, voice: Optional[str] = None, lang: Optional[str] = None) -> Optional[bytes]:
    if not config.llm_enabled() or config.AI_PROVIDER != "openai":
        return None
    text = text.strip()[:4000]
    if not text:
        return None
    key = hashlib.sha1(f"{config.OPENAI_TTS_MODEL}|{voice or config.OPENAI_TTS_VOICE}|{lang}|{text}".encode()).hexdigest()
    path: Path = TTS_DIR / f"{key}.mp3"
    if path.exists():
        return path.read_bytes()
    c = llm.client()
    try:
        resp = c.audio.speech.create(
            model=config.OPENAI_TTS_MODEL,
            voice=voice or config.OPENAI_TTS_VOICE,
            input=text,
            instructions=STYLE + (f" The listener prefers {lang}." if lang else ""),
            response_format="mp3",
        )
        data = resp.content if hasattr(resp, "content") else resp.read()
        path.write_bytes(data)
        return data
    except Exception as exc:  # noqa: BLE001
        log.warning("tts failed: %s", exc)
        return None
