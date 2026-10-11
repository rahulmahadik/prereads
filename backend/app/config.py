"""Runtime configuration. Everything is env-driven so the same code runs in
three modes:

  DEMO=1          -> no network, routes served from the precomputed cache only
  keys present    -> live OpenAI (readiness, prerequisites, scan, ask) and
                     live NLB (availability, demand) with cache in front
  partial keys    -> whatever is missing falls back (NLB -> Open Library ->
                     demo availability; OpenAI -> heuristics)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT.parent / ".env")
load_dotenv(ROOT / ".env")


def _flag(name: str, default: str = "0") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


DEMO: bool = _flag("DEMO", "0")

# AI provider: ollama (local models, default) | openai | none (heuristics only)
AI_PROVIDER: str = os.getenv("AI_PROVIDER", "ollama").strip().lower()
OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
LOCAL_LLM_MODEL: str = os.getenv("LOCAL_LLM_MODEL", "gpt-oss:20b").strip()              # interactive
LOCAL_LLM_MODEL_HEAVY: str = os.getenv("LOCAL_LLM_MODEL_HEAVY", "gpt-oss:120b").strip()  # precompute, pairwise judgments
LOCAL_VISION_MODEL: str = os.getenv("LOCAL_VISION_MODEL", "qwen2.5vl:7b").strip()
LOCAL_EMBED_MODEL: str = os.getenv("LOCAL_EMBED_MODEL", "nomic-embed-text").strip()
# Tried in order when a configured model is not pulled yet, so the app degrades instead of breaking.
LOCAL_LLM_FALLBACKS: list[str] = [m.strip() for m in os.getenv("LOCAL_LLM_FALLBACKS", "gemma3:12b,qwen3.6:35b-a3b").split(",") if m.strip()]
LOCAL_HEAVY_FALLBACKS: list[str] = [m.strip() for m in os.getenv("LOCAL_HEAVY_FALLBACKS", "gemma3:12b,qwen3.6:35b-a3b").split(",") if m.strip()]
LOCAL_VISION_FALLBACKS: list[str] = [m.strip() for m in os.getenv("LOCAL_VISION_FALLBACKS", "gemma3:12b").split(",") if m.strip()]
LOCAL_TIMEOUT: float = float(os.getenv("LOCAL_TIMEOUT", "60"))

OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "").strip()
# Verify the exact model string in your OpenAI dashboard on the day; any
# current GPT-5.x/6.x model that supports structured outputs and vision works.
OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5.5").strip()
OPENAI_VISION_MODEL: str = os.getenv("OPENAI_VISION_MODEL", OPENAI_MODEL).strip()
# Natural voice. Any current OpenAI TTS model works; check the dashboard for the name.
OPENAI_TTS_MODEL: str = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts").strip()
OPENAI_TTS_VOICE: str = os.getenv("OPENAI_TTS_VOICE", "coral").strip()

NLB_API_KEY: str = os.getenv("NLB_API_KEY", "").strip()
NLB_APP_CODE: str = os.getenv("NLB_APP_CODE", "").strip()
NLB_BASE: str = os.getenv("NLB_BASE", "https://openweb.nlb.gov.sg/api/v2/Catalogue").rstrip("/")
# Catalogue v2 endpoints (from NLB's OpenAPI): SearchTitles, GetTitles,
# GetTitleDetails, GetAvailabilityInfo, GetNewTitles, GetMostCheckoutsTrendsTitles.
NLB_TRENDS_PATH: str = os.getenv("NLB_TRENDS_PATH", "GetMostCheckoutsTrendsTitles").strip("/")
NLB_TRENDS_DURATION: str = os.getenv("NLB_TRENDS_DURATION", "past30days")

OPENLIBRARY_BASE: str = "https://openlibrary.org"

DATA_DIR: Path = ROOT / "data"
CACHE_DIR: Path = DATA_DIR / "cache"
ROUTES_DIR: Path = CACHE_DIR / "routes"
ROUTES_DIR.mkdir(parents=True, exist_ok=True)

HTTP_TIMEOUT: float = float(os.getenv("HTTP_TIMEOUT", "12"))


# Runtime overrides (set from the Settings sheet via /api/mode). None = use .env.
RUNTIME: dict[str, Optional[bool]] = {"demo": None, "use_llm": None, "use_nlb": None}


def effective_demo() -> bool:
    return DEMO if RUNTIME["demo"] is None else bool(RUNTIME["demo"])


def has_openai_key() -> bool:
    return bool(OPENAI_API_KEY)


def has_nlb_key() -> bool:
    return bool(NLB_API_KEY and NLB_APP_CODE)


def ollama_reachable() -> bool:
    from . import llm  # local import: llm imports config

    return llm.ollama_up()


def ai_available() -> bool:
    """Is the configured provider usable right now (key present / Ollama answering)?"""
    if AI_PROVIDER == "openai":
        return has_openai_key()
    if AI_PROVIDER == "ollama":
        return ollama_reachable()
    return False


def llm_enabled() -> bool:
    if effective_demo() or not ai_available():
        return False
    return True if RUNTIME["use_llm"] is None else bool(RUNTIME["use_llm"])


def nlb_enabled() -> bool:
    if effective_demo() or not has_nlb_key():
        return False
    return True if RUNTIME["use_nlb"] is None else bool(RUNTIME["use_nlb"])


def mode() -> str:
    if effective_demo():
        return "demo"
    parts = []
    parts.append(AI_PROVIDER if llm_enabled() else "heuristics")
    parts.append("nlb" if nlb_enabled() else "openlibrary+demo-availability")
    return "+".join(parts)


def mode_info() -> dict:
    return {
        "demo": effective_demo(),
        "provider": AI_PROVIDER,
        "openai_key": has_openai_key(),
        "ollama": ollama_info() if AI_PROVIDER == "ollama" else None,
        "nlb_key": has_nlb_key(),
        "use_llm": llm_enabled(),
        "use_nlb": nlb_enabled(),
        "mode": mode(),
        "env_demo": DEMO,
    }


def ollama_info() -> dict:
    from . import llm

    return llm.ollama_status()
