"""Local speech-to-text with faster-whisper (large-v3-turbo). Nothing leaves the device.

The model loads on first use (and downloads once, ~1.6 GB). Returns None when
faster-whisper is not installed or fails, and the browser's SpeechRecognition takes over.
"""
from __future__ import annotations

import io
import logging
import os
import threading
from typing import Optional

log = logging.getLogger("prereads.stt")

STT_MODEL = os.getenv("STT_MODEL", "large-v3-turbo").strip()
STT_DEVICE = os.getenv("STT_DEVICE", "cpu").strip()          # faster-whisper has no Metal backend; cpu + int8 is quick on Apple silicon
STT_COMPUTE = os.getenv("STT_COMPUTE", "int8").strip()

_model = None
_lock = threading.Lock()


def available() -> bool:
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _load():
    global _model
    with _lock:
        if _model is None:
            from faster_whisper import WhisperModel

            _model = WhisperModel(STT_MODEL, device=STT_DEVICE, compute_type=STT_COMPUTE)
        return _model


def transcribe(audio: bytes, language: Optional[str] = "en") -> Optional[str]:
    if not audio or not available():
        return None
    try:
        segments, _ = _load().transcribe(io.BytesIO(audio), language=language, vad_filter=True, beam_size=1)
        text = " ".join(s.text.strip() for s in segments).strip()
        return text or None
    except Exception as exc:  # noqa: BLE001
        log.warning("stt failed: %s", exc)
        return None
