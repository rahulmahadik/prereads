"""A tiny time-based cache for read-mostly endpoints (the target list, library list, suggestions):
many readers at once get the same answer from memory instead of each rebuilding it from disk."""
from __future__ import annotations

import functools
import threading
import time
from typing import Any, Callable


def ttl_cache(seconds: float) -> Callable:
    def wrap(fn: Callable) -> Callable:
        store: dict[Any, tuple[float, Any]] = {}
        lock = threading.Lock()
        building: dict[Any, threading.Lock] = {}     # one builder per key; a crowd waits for its answer

        @functools.wraps(fn)
        def inner(*args, **kwargs):
            key = (args, tuple(sorted(kwargs.items())))
            with lock:
                hit = store.get(key)
                if hit and time.monotonic() - hit[0] < seconds:
                    return hit[1]
                key_lock = building.setdefault(key, threading.Lock())
            with key_lock:
                with lock:                                # built while this request waited?
                    hit = store.get(key)
                    if hit and time.monotonic() - hit[0] < seconds:
                        return hit[1]
                now = time.monotonic()
                value = fn(*args, **kwargs)
            with lock:
                store[key] = (now, value)
                if len(store) > 256:              # small and bounded: drop the oldest entries
                    for k, _ in sorted(store.items(), key=lambda kv: kv[1][0])[:64]:
                        store.pop(k, None)
            return value

        inner.cache_clear = store.clear         # type: ignore[attr-defined]
        return inner

    return wrap
