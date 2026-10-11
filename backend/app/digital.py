"""eBook / audiobook availability from NLB's OverDrive (Libby) catalogue.

Uses OverDrive's public "thunder" API with library key ``nlb`` (no API key needed).
Light, user-triggered lookups only; cached in memory and on disk. Never raises.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import quote

import httpx

from .catalog import title_matches

BASE = "https://thunder.api.overdrive.com/v2/libraries/nlb/media"
SITE = "https://nlb.overdrive.com"
UA = "PreReads makeathon prototype"
TTL = 6 * 3600
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cache" / "digital"
_mem: dict[str, tuple[float, dict]] = {}


def search_url(title: str) -> str:
    return f"{SITE}/search?query={quote(title)}"


def _key(title: str, author: str) -> str:
    return hashlib.sha1(f"{title.lower().strip()}|{author.lower().strip()}".encode()).hexdigest()[:20]


def _author_ok(author: str, item: dict) -> bool:
    if not author.strip():
        return True
    names = " ".join(c.get("name", "") for c in item.get("creators", []) or []) or str(item.get("firstCreatorName", ""))
    names = names.lower()
    toks = [t for t in re.findall(r"[a-z]+", author.lower()) if len(t) > 2]
    return not toks or toks[-1] in names or any(t in names for t in toks)


def _parse(items: list[dict], title: str, author: str) -> dict:
    out: dict[str, Optional[dict]] = {"ebook": None, "audiobook": None}
    for it in items:
        kind = (it.get("type") or {}).get("id")
        if kind not in out:
            continue
        if not title_matches(title, str(it.get("title", ""))) or not _author_ok(author, it):
            continue
        owned = int(it.get("ownedCopies") or 0)
        avail = int(it.get("availableCopies") or 0)
        holds = int(it.get("holdsCount") or 0)
        rid = it.get("reserveId") or it.get("id")
        cur = out[kind]
        if cur is None:
            out[kind] = {"owned": owned, "available": avail, "holds": holds,
                         "url": f"{SITE}/media/{rid}" if rid else search_url(title)}
        else:  # several editions of the same format: add up
            cur["owned"] += owned
            cur["available"] += avail
            cur["holds"] += holds
    return {**out, "source": "overdrive", "live": True}


def _read_disk(k: str) -> Optional[dict]:
    try:
        p = CACHE_DIR / f"{k}.json"
        if p.exists():
            d = json.loads(p.read_text())
            if time.time() - d["ts"] < TTL:
                return d["data"]
    except Exception:
        pass
    return None


def _write_disk(k: str, data: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        (CACHE_DIR / f"{k}.json").write_text(json.dumps({"ts": time.time(), "data": data}))
    except Exception:
        pass


def lookup(title: str, author: str = "") -> dict[str, Any]:
    fail: dict[str, Any] = {"live": False, "search_url": search_url(title or "")}
    title = (title or "").strip()
    if not title:
        return fail
    k = _key(title, author or "")
    hit = _mem.get(k)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    disk = _read_disk(k)
    if disk:
        _mem[k] = (time.time(), disk)
        return disk
    try:
        r = httpx.get(BASE, params={"query": f"{title} {author}".strip(), "perPage": 12},
                      headers={"User-Agent": UA, "Accept": "application/json"},
                      timeout=10.0, follow_redirects=True)
        r.raise_for_status()
        data = _parse(r.json().get("items", []) or [], title, author or "")
        data["search_url"] = search_url(title)
    except Exception:
        return fail  # failures are not cached
    _mem[k] = (time.time(), data)
    _write_disk(k, data)
    return data
