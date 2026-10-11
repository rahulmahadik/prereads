"""Local embeddings (nomic-embed-text via Ollama) with an on-disk cache keyed by text hash.

Used to shortlist discovery candidates and to find a book's neighbours. Every function
returns None / [] when the embedding model is unreachable so callers fall back to keywords.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from typing import Optional

from . import config, llm

log = logging.getLogger("prereads.embeddings")

EMB_DIR = config.CACHE_DIR / "embeddings"
EMB_DIR.mkdir(parents=True, exist_ok=True)

_store: dict[str, list[float]] = {}
_loaded_for: Optional[str] = None
_lock = threading.Lock()


def _file(model: str):
    return EMB_DIR / (model.replace(":", "_").replace("/", "_") + ".json")


def _key(model: str, text: str) -> str:
    return hashlib.sha1(f"{model}|{text}".encode()).hexdigest()


def _load(model: str) -> None:
    global _loaded_for
    if _loaded_for == model:
        return
    _store.clear()
    p = _file(model)
    if p.exists():
        try:
            _store.update(json.loads(p.read_text()))
        except Exception:  # noqa: BLE001
            log.warning("embedding cache unreadable; starting fresh")
    _loaded_for = model


def _flush(model: str) -> None:
    _file(model).write_text(json.dumps(_store))


def available() -> bool:
    return not config.effective_demo() and config.AI_PROVIDER == "ollama" and llm.ollama_up()


def vectors(texts: list[str], prefix: str = "search_document: ") -> Optional[list[list[float]]]:
    """Embeddings for texts (cached). None if the model is unavailable."""
    if not texts or not available():
        return None
    model = llm.resolve_model("embed")
    with _lock:
        _load(model)
        keys = [_key(model, prefix + t) for t in texts]
        missing = [(k, t) for k, t in zip(keys, texts) if k not in _store]
        if missing:
            got = llm.embed([prefix + t for _, t in missing])
            if got is None:
                return None
            for (k, _), v in zip(missing, got):
                _store[k] = v
            _flush(model)
        return [_store[k] for k in keys]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def rank(query: str, items: list[tuple[str, str]], top_k: int = 40, *, query_prefix: str = "search_query: ") -> Optional[list[tuple[str, float]]]:
    """items = [(id, text)]. Returns [(id, centred cosine)] best first, or None when embeddings are unavailable.
    Centred cosines: a clear match is ~0.2-0.3, unrelated ~0."""
    if not items:
        return []
    q = vectors([query], prefix=query_prefix)
    d = vectors([t for _, t in items])
    if q is None or d is None:
        return None
    # Mean-centre against the pool: removes the shared "it's a book" direction, so generic
    # "hub" titles stop matching every query.
    n = len(d)
    mean = [sum(col) / n for col in zip(*d)]
    centre = lambda v: [a - m for a, m in zip(v, mean)]  # noqa: E731
    qc = centre(q[0])
    scored = [(i, cosine(qc, centre(v))) for (i, _), v in zip(items, d)]
    scored.sort(key=lambda x: -x[1])
    return scored[:top_k]


def warm(texts: list[str]) -> None:
    """Fill the cache in the background so the first request is fast."""
    try:
        vectors(texts)
    except Exception as exc:  # noqa: BLE001
        log.warning("embedding warm-up failed: %s", exc)
