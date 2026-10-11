"""AI provider layer. Every call returns a validated Pydantic object or None.

AI_PROVIDER=ollama (default) talks to open-source models through Ollama's OpenAI-compatible
API; AI_PROVIDER=openai uses OpenAI's API; none disables AI so the engine uses its
heuristics. Both paths share one interface (`structured`), validate every reply with
Pydantic, and retry once on invalid JSON. Nothing here may raise into the request path.

Layer: ai. The only module that talks to a language model. Callers in services/ check
`config.llm_enabled()` first and use a heuristic when a call returns None.
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Optional, Type, TypeVar

import httpx
from pydantic import BaseModel

from ..core import config
from ..core.models import Book, CandidateList, Judgment, Readiness, ScanResult

log = logging.getLogger("prereads.llm")
T = TypeVar("T", bound=BaseModel)

_client = None

TEMP_SCORE = 0.2     # scoring and judgments
TEMP_PROPOSE = 0.7   # proposals

# precompute.py and eval_paths.py set this so readiness, candidates and pairwise judgments
# use the heavy model; interactive requests keep the fast one.
HEAVY = False


def _tier() -> str:
    return "heavy" if HEAVY else "llm"


# ------------------------------------------------------------------ ollama state
_tags: dict = {"at": 0.0, "models": None}


def _fetch_tags() -> Optional[list[str]]:
    try:
        r = httpx.get(f"{config.OLLAMA_BASE_URL}/api/tags", timeout=2.0)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]
    except Exception:  # noqa: BLE001
        return None


def installed_models(max_age: float = 15.0) -> Optional[list[str]]:
    """Model names Ollama has pulled, or None if it is not answering. Cached for max_age
    seconds because health, mode and every resolve_model() call ask."""
    if time.time() - _tags["at"] > max_age:
        _tags["models"], _tags["at"] = _fetch_tags(), time.time()
    return _tags["models"]


def ollama_up() -> bool:
    return installed_models() is not None


def _has(model: str, have: list[str]) -> bool:
    # Ollama lists an untagged pull as "name:latest".
    return model in have or (":" not in model and f"{model}:latest" in have)


def resolve_model(kind: str = "llm") -> str:
    """The configured model if pulled, else the first installed fallback."""
    wanted, fallbacks = {
        "llm": (config.LOCAL_LLM_MODEL, config.LOCAL_LLM_FALLBACKS),
        "chat": (config.LOCAL_CHAT_MODEL, [config.LOCAL_LLM_MODEL, *config.LOCAL_LLM_FALLBACKS]),
        "heavy": (config.LOCAL_LLM_MODEL_HEAVY, config.LOCAL_HEAVY_FALLBACKS),
        "vision": (config.LOCAL_VISION_MODEL, config.LOCAL_VISION_FALLBACKS),
        "embed": (config.LOCAL_EMBED_MODEL, []),
    }[kind]
    have = installed_models() or []
    # Fallbacks keep the app working on a machine that has not pulled the big models yet
    # (a missing 120b heavy model degrades to gemma3:12b instead of failing every call).
    for m in [wanted, *fallbacks]:
        if _has(m, have):
            return m
    # Nothing installed (or Ollama down): return the configured name so the call fails
    # loudly in the log and the caller's heuristic takes over.
    return wanted


def ollama_status() -> dict:
    have = installed_models()
    out = {"reachable": have is not None, "base_url": config.OLLAMA_BASE_URL, "models": {}}
    for kind in ("llm", "heavy", "vision", "embed"):
        m = resolve_model(kind)
        out["models"][kind] = {"name": m, "installed": bool(have) and _has(m, have)}
    return out


# ------------------------------------------------------------------ client
def client():
    """Shared OpenAI-compatible client (Ollama's /v1 or OpenAI). Created on first use while
    AI is enabled; None until then."""
    global _client
    if _client is None and config.llm_enabled():
        from openai import OpenAI  # imported lazily so demo mode needs no key

        if config.AI_PROVIDER == "ollama":
            _client = OpenAI(base_url=f"{config.OLLAMA_BASE_URL}/v1", api_key="ollama", timeout=config.LOCAL_TIMEOUT, max_retries=0)
        else:
            _client = OpenAI(api_key=config.OPENAI_API_KEY)
    return _client


def _model_for(kind: str) -> str:
    if config.AI_PROVIDER == "ollama":
        return resolve_model(kind)
    return config.OPENAI_VISION_MODEL if kind == "vision" else config.OPENAI_MODEL


def _schema_format(schema: Type[T]) -> dict:
    return {"type": "json_schema", "json_schema": {"name": schema.__name__, "strict": True, "schema": schema.model_json_schema()}}


def structured(
    schema: Type[T],
    system: str,
    user: str,
    *,
    kind: str = "llm",
    temperature: float = TEMP_SCORE,
    image_url: Optional[str] = None,
) -> Optional[T]:
    """One validated structured reply, or None. Retries once on invalid JSON."""
    c = client()
    if c is None:
        return None
    content: object = user
    if image_url:
        content = [{"type": "text", "text": user}, {"type": "image_url", "image_url": {"url": image_url}}]
    messages = [{"role": "system", "content": system}, {"role": "user", "content": content}]
    model = _model_for(kind)
    for attempt in (1, 2):
        try:
            resp = c.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                response_format=_schema_format(schema),
            )
            raw = (resp.choices[0].message.content or "").strip()
            return schema.model_validate_json(raw)
        except Exception as exc:  # noqa: BLE001 - never break the request path
            log.warning("LLM call failed (%s, %s, try %d): %s", schema.__name__, model, attempt, exc)
    return None


def text(system: str, user: str, *, kind: str = "llm", temperature: float = 0.4) -> Optional[str]:
    """A plain-text reply, or None."""
    c = client()
    if c is None:
        return None
    try:
        resp = c.chat.completions.create(
            model=_model_for(kind),
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=temperature,
        )
        return (resp.choices[0].message.content or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        log.warning("LLM text call failed: %s", exc)
        return None


def embed(texts: list[str]) -> Optional[list[list[float]]]:
    """Embeddings from Ollama (/api/embeddings). None when unavailable."""
    if config.AI_PROVIDER != "ollama" or not ollama_up():
        return None
    model = resolve_model("embed")
    out: list[list[float]] = []
    try:
        with httpx.Client(timeout=config.LOCAL_TIMEOUT) as h:
            for t in texts:
                r = h.post(f"{config.OLLAMA_BASE_URL}/api/embeddings", json={"model": model, "prompt": t})
                r.raise_for_status()
                out.append(r.json()["embedding"])
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("embedding failed: %s", exc)
        return None


READINESS_SYSTEM = (
    "You are a public-library readers' advisor in Singapore. Given a book's "
    "metadata, estimate how ready a general adult reader must be. Level 1 = "
    "anyone can start today; 3 = needs some familiarity with the field; 5 = "
    "specialist or very dense. Hours = typical reading time for an average adult. "
    "assumed_concepts are 3-6 short noun phrases a reader should already know. "
    "one_line tells the reader, plainly and warmly, what they need going in."
)


def readiness(book: Book) -> Optional[Readiness]:
    user = json.dumps(
        {
            "title": book.title,
            "author": book.author,
            "year": book.year,
            "pages": book.pages,
            "subjects": book.subjects[:12],
            "summary": book.summary[:1500],
        },
        ensure_ascii=False,
    )
    return structured(Readiness, READINESS_SYSTEM, user, kind=_tier(), temperature=TEMP_SCORE)


CANDIDATES_SYSTEM = (
    "You are a readers' advisor building a reading line for a target book. "
    "Propose real, widely available published books only (no inventions, no "
    "articles). 'before' = 6 easier or more introductory books that prepare a "
    "reader for the target (concept on-ramps, friendlier treatments, shorter "
    "primers). 'after' = 5 books a reader would naturally go to next (deeper, "
    "adjacent, or the author's follow-on). Each item: title, author, why (one "
    "sentence, plain, specific to the target). Prefer books likely to be in a "
    "large public library. Never include the target itself."
)


def candidates(target: Book) -> Optional[CandidateList]:
    user = json.dumps(
        {"target": {"title": target.title, "author": target.author, "subjects": target.subjects[:10], "summary": target.summary[:1200]}},
        ensure_ascii=False,
    )
    return structured(CandidateList, CANDIDATES_SYSTEM, user, kind=_tier(), temperature=TEMP_PROPOSE)


JUDGE_SYSTEM = (
    "You judge reading order between two books for a public-library reader. "
    "relation: prepares_for = reading A first makes B noticeably easier; "
    "same_level = similar difficulty, either order; follows = A is the natural "
    "next book after B; unrelated. confidence 0-1. reason: one sentence a "
    "librarian would say to a patron, mentioning the specific concept or skill."
)


def judge(a: Book, b: Book, ra: Optional[Readiness], rb: Optional[Readiness]) -> Optional[Judgment]:
    user = json.dumps(
        {
            "A": {"title": a.title, "author": a.author, "level": ra.level if ra else None, "concepts": ra.assumed_concepts if ra else []},
            "B": {"title": b.title, "author": b.author, "level": rb.level if rb else None, "concepts": rb.assumed_concepts if rb else []},
            "question": "Does A prepare a reader for B?",
        },
        ensure_ascii=False,
    )
    return structured(Judgment, JUDGE_SYSTEM, user, kind=_tier(), temperature=TEMP_SCORE)


SCAN_SYSTEM = (
    "Read the book cover or spine in the image. Return the exact title and "
    "author as printed, the ISBN if a barcode/number is legible, and your "
    "confidence 0-1. If no book is visible, title='' and confidence=0."
)


def scan(image_bytes: bytes, mime: str = "image/jpeg") -> Optional[ScanResult]:
    b64 = base64.b64encode(image_bytes).decode()
    return structured(ScanResult, SCAN_SYSTEM, "Identify this book.", kind="vision", temperature=TEMP_SCORE, image_url=f"data:{mime};base64,{b64}")


LANG_NAMES = {"zh": "Simplified Chinese (中文)", "ms": "Bahasa Melayu", "ta": "Tamil (தமிழ்)"}


def with_lang(system: str, lang: Optional[str]) -> str:
    """Append the reader-language instruction to a system prompt (no-op for English or unknown codes)."""
    name = LANG_NAMES.get((lang or "").strip().lower()[:2])
    if not name:
        return system
    return f"{system} Write every reader-facing sentence (why, reason, answer, messages) in {name}. Keep book titles and author names exactly as published."


ASK_SYSTEM = (
    "You are PreReads, a readers' advisor. Answer ONLY from the route JSON given. "
    "Never add books that are not in the route. Be warm, plain, and brief "
    "(max 90 words). If asked about time, use the hours on each stop. If asked "
    "about large print or audio, say what the route data shows and suggest "
    "asking staff for large-print editions."
)


def ask(route_json: str, question: str, lang: Optional[str] = None) -> Optional[str]:
    # grounded answers in the Ask sheet: the fast chat tier keeps them to a few seconds
    return text(with_lang(ASK_SYSTEM, lang), f"ROUTE:\n{route_json}\n\nQUESTION: {question}", kind="chat")
