"""Natural voice: text -> speech, cached on disk.

AI_PROVIDER=ollama (default): Kokoro (kokoro-onnx, model files fetched once into
data/models) if available, else the macOS `say` voice, so it still works with no download.
AI_PROVIDER=openai: OpenAI TTS (mp3). Returns None when nothing is available and the
frontend falls back to the browser's built-in voices, so "Listen" always works.

Layer: ai. Served by api/routes_media.py (/api/tts). Cache: data/cache/tts, keyed by text + voice.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional

import httpx

from ..core import config
from . import llm

log = logging.getLogger("prereads.tts")

TTS_DIR = config.CACHE_DIR / "tts"
TTS_DIR.mkdir(parents=True, exist_ok=True)
MODEL_DIR = config.DATA_DIR / "models"
KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
LOCAL_TTS_VOICE = os.getenv("LOCAL_TTS_VOICE", "bf_emma").strip()   # warm British English; af_heart is the US alternative
MAC_VOICE = os.getenv("MAC_SAY_VOICE", "Samantha").strip()

_kokoro = None
_kokoro_failed = False
_lock = threading.Lock()

# Voices are made one at a time. Past this many being made or waiting, a new one answers "busy" at
# once and the page reads aloud with the browser voice instead of queueing behind other readers.
TTS_MAX_PENDING = int(os.getenv("TTS_MAX_PENDING", "3"))
_pending = 0
_pending_lock = threading.Lock()


class Busy(Exception):
    """Every voice slot is taken; try the browser voice."""

# A warm, unhurried librarian. Kept short: the instructions field steers tone.
STYLE = (
    "Speak like a friendly public librarian in Singapore: warm, clear, unhurried, "
    "slightly conversational. Pause briefly between sentences. Pronounce book titles "
    "and author names carefully."
)


def _kokoro_engine():
    """Kokoro, downloading the model files once. None if unavailable."""
    global _kokoro, _kokoro_failed
    if _kokoro is not None or _kokoro_failed:
        return _kokoro
    with _lock:
        if _kokoro is not None or _kokoro_failed:
            return _kokoro
        try:
            from kokoro_onnx import Kokoro

            MODEL_DIR.mkdir(parents=True, exist_ok=True)
            for name, url in KOKORO_FILES.items():
                dest = MODEL_DIR / name
                if not dest.exists():
                    log.info("downloading %s (one time)", name)
                    tmp = dest.with_suffix(".part")
                    with httpx.stream("GET", url, follow_redirects=True, timeout=300) as r:
                        r.raise_for_status()
                        with open(tmp, "wb") as f:
                            for chunk in r.iter_bytes():
                                f.write(chunk)
                    tmp.rename(dest)
            _kokoro = Kokoro(str(MODEL_DIR / "kokoro-v1.0.onnx"), str(MODEL_DIR / "voices-v1.0.bin"))
        except Exception as exc:  # noqa: BLE001
            log.warning("kokoro unavailable: %s", exc)
            _kokoro_failed = True
        return _kokoro


def _speak_kokoro(text: str, voice: Optional[str]) -> Optional[bytes]:
    k = _kokoro_engine()
    if k is None:
        return None
    import io

    import soundfile as sf

    samples, rate = k.create(text, voice=voice or LOCAL_TTS_VOICE, speed=0.96, lang="en-gb" if (voice or LOCAL_TTS_VOICE).startswith("b") else "en-us")
    buf = io.BytesIO()
    sf.write(buf, samples, rate, format="WAV")
    return buf.getvalue()


def _speak_say(text: str) -> Optional[bytes]:
    if not (shutil.which("say") and shutil.which("afconvert")):
        return None
    with tempfile.TemporaryDirectory() as d:
        aiff, wav = Path(d) / "o.aiff", Path(d) / "o.wav"
        subprocess.run(["say", "-v", MAC_VOICE, "-o", str(aiff), text], check=True, timeout=60)
        subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@22050", str(aiff), str(wav)], check=True, timeout=60)
        return wav.read_bytes()


def synthesize(text: str, voice: Optional[str] = None, lang: Optional[str] = None) -> Optional[tuple[bytes, str]]:
    """(audio bytes, media type) or None."""
    if config.effective_demo() or config.AI_PROVIDER == "none":
        return None
    text = text.strip()[:4000]
    if not text:
        return None
    local = config.AI_PROVIDER == "ollama"
    engine = f"kokoro:{voice or LOCAL_TTS_VOICE}" if local else f"{config.OPENAI_TTS_MODEL}:{voice or config.OPENAI_TTS_VOICE}"
    ext, media = ("wav", "audio/wav") if local else ("mp3", "audio/mpeg")
    key = hashlib.sha1(f"{engine}|{lang}|{text}".encode()).hexdigest()
    path: Path = TTS_DIR / f"{key}.{ext}"
    if path.exists():
        return path.read_bytes(), media
    global _pending
    with _pending_lock:
        if _pending >= TTS_MAX_PENDING:
            raise Busy()
        _pending += 1
    try:
        if local:
            data = _speak_kokoro(text, voice) or _speak_say(text)
        else:
            data = _speak_openai(text, voice, lang)
    except Exception as exc:  # noqa: BLE001
        log.warning("tts failed: %s", exc)
        return None
    finally:
        with _pending_lock:
            _pending -= 1
    if not data:
        return None
    path.write_bytes(data)
    _trim_cache()
    return data, media


TTS_CACHE_MAX = int(os.getenv("TTS_CACHE_MAX_MB", "500")) * 1_000_000


def _trim_cache() -> None:
    """Keep the voice cache under TTS_CACHE_MAX: drop the oldest clips first (a flood of unique
    texts must not fill the disk)."""
    try:
        files = sorted((f for f in TTS_DIR.iterdir() if f.is_file()), key=lambda f: f.stat().st_mtime)
        total = sum(f.stat().st_size for f in files)
        while files and total > TTS_CACHE_MAX:
            f = files.pop(0)
            total -= f.stat().st_size
            f.unlink(missing_ok=True)
    except OSError as exc:
        log.warning("tts cache trim failed: %s", exc)


def _speak_openai(text: str, voice: Optional[str], lang: Optional[str]) -> Optional[bytes]:
    if not config.llm_enabled():
        return None
    c = llm.client()
    resp = c.audio.speech.create(
        model=config.OPENAI_TTS_MODEL,
        voice=voice or config.OPENAI_TTS_VOICE,
        input=text,
        instructions=STYLE + (f" The listener prefers {lang}." if lang else ""),
        response_format="mp3",
    )
    return resp.content if hasattr(resp, "content") else resp.read()
