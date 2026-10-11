"""Legally free online copies: Project Gutenberg (public domain) and Open Library / Internet Archive.

Light, user-triggered lookups; cached on disk for 7 days. Never raises: any failure gives {}
(and is not cached). Layer: integrations. Served by api/routes_library.py (/api/online).
Cache: data/cache/online.
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Optional

import httpx

from ..core import config
from .catalog import title_matches

GUTENDEX = "https://gutendex.com/books/"
OPENLIB = "https://openlibrary.org/search.json"
UA = "PreReads makeathon prototype"
TTL = 7 * 86400
CACHE_DIR = config.CACHE_DIR / "online"
_mem: dict[str, tuple[float, dict]] = {}


def _key(title: str, author: str) -> str:
    return hashlib.sha1(f"{title.lower().strip()}|{author.lower().strip()}".encode()).hexdigest()[:20]


def _surname(author: str) -> str:
    toks = re.findall(r"[a-z]+", author.lower())
    return toks[-1] if toks else ""


def _author_ok(author: str, names: list[str]) -> bool:
    s = _surname(author)
    if not s:
        return True
    return s in " ".join(names).lower()


def _get(url: str, params: dict) -> dict:
    r = httpx.get(url, params=params, headers={"User-Agent": UA, "Accept": "application/json"},
                  timeout=20.0, follow_redirects=True)
    r.raise_for_status()
    return r.json()


def _gutenberg(title: str, author: str) -> Optional[dict]:
    data = _get(GUTENDEX, {"search": f"{title} {author}".strip()})
    for b in data.get("results", []) or []:
        if not title_matches(title, str(b.get("title", ""))):
            continue
        if not _author_ok(author, [a.get("name", "") for a in b.get("authors", []) or []]):
            continue
        fmts = b.get("formats") or {}
        html = next((v for k, v in fmts.items() if k.startswith("text/html")), None)
        epub = next((v for k, v in fmts.items() if k.startswith("application/epub")), None)
        bid = b.get("id")
        if not bid:
            continue
        return {"url": f"https://www.gutenberg.org/ebooks/{bid}",
                "read_url": html or epub or f"https://www.gutenberg.org/ebooks/{bid}",
                "formats": [n for n, v in (("html", html), ("epub", epub)) if v]}
    return None


def _openlibrary(title: str, author: str) -> Optional[dict]:
    params = {"q": title, "fields": "key,title,author_name,ebook_access,ia,lending_identifier_s,has_fulltext",
              "limit": 5}
    if author.strip():
        params["author"] = author
    data = _get(OPENLIB, params)
    best: Optional[dict] = None
    for d in data.get("docs", []) or []:
        if not title_matches(title, str(d.get("title", ""))):
            continue
        if not _author_ok(author, d.get("author_name") or []):
            continue
        access = d.get("ebook_access")
        if access not in ("public", "borrowable"):
            continue
        page = f"https://openlibrary.org{d.get('key', '')}"
        if access == "public":
            ia = (d.get("ia") or [None])[0]
            return {"access": "public", "url": page,
                    "read_url": f"https://archive.org/details/{ia}" if ia else f"{page}?mode=everything"}
        best = best or {"access": "borrowable", "url": page, "read_url": page}
    return best


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
    """{"gutenberg": {...}|None, "openlibrary": {...}|None}; {} on any failure."""
    title, author = (title or "").strip(), (author or "").strip()
    if not title:
        return {}
    k = _key(title, author)
    hit = _mem.get(k)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    disk = _read_disk(k)
    if disk is not None:
        _mem[k] = (time.time(), disk)
        return disk
    data: dict[str, Any] = {}
    failed = 0
    for name, fn in (("gutenberg", _gutenberg), ("openlibrary", _openlibrary)):
        try:
            data[name] = fn(title, author)
        except Exception:
            data[name] = None
            failed += 1
    if failed:
        # a slow or failed source is remembered for an hour (memory only), so the next visit
        # doesn't wait again; it is retried after that
        _mem[k] = (time.time() - TTL + 3600, {} if failed == 2 else data)
        return {} if failed == 2 else data
    _mem[k] = (time.time(), data)
    _write_disk(k, data)
    return data


# --- First chapter of a public-domain Gutenberg book (for the in-app reader) ---

TEXT_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"
MAX_CHARS = 20000
_ORD = r"(?:FIRST|1ST|ONE|I|1)"
# First-section headings, most specific unit first: a chapter beats a book that only holds chapters.
_FIRST = [
    re.compile(rf"^\s*(?:THE\s+)?(?:CHAPTER\s+{_ORD}|{_ORD}\s+CHAPTER)\b[\s.:]*(?:\S.*)?$", re.I),
    re.compile(rf"^\s*(?:THE\s+)?(?:BOOK\s+{_ORD}|{_ORD}\s+BOOK)\b[\s.:]*(?:\S.*)?$", re.I),
    re.compile(rf"^\s*(?:THE\s+)?(?:PART\s+{_ORD}|{_ORD}\s+PART)\b[\s.:]*(?:\S.*)?$", re.I),
]
_ANY_HEAD = re.compile(
    r"^\s*(?:THE\s+)?(?:(?:CHAPTER|BOOK|PART)\s+[IVXLC\d]+|"
    r"(?:FIRST|SECOND|THIRD|FOURTH|FIFTH|SIXTH|SEVENTH|EIGHTH|NINTH|TENTH|\d+(?:ST|ND|RD|TH)?)"
    r"\s+(?:CHAPTER|BOOK|PART))\b[\s.:]*(?:\S.{0,80})?$", re.I)
_SMALL = {"of", "the", "and", "in", "on", "to", "a", "an", "for", "or"}


def _nice(s: str) -> str:
    words = re.sub(r"\s+", " ", s.strip()).lower().split(" ")
    out = [w if (i and w in _SMALL) else w[:1].upper() + w[1:] for i, w in enumerate(words)]
    s = " ".join(out)
    s = re.sub(r"\b(Chapter|Book|Part) ([ivxlc]+)\b", lambda m: f"{m[1]} {m[2].upper()}", s)
    return re.sub(r"([.:]) ([a-z])", lambda m: f"{m[1]} {m[2].upper()}", s)


def _paragraphs(lines: list[str]) -> list[str]:
    paras, cur = [], []
    for ln in lines + [""]:
        if ln.strip():
            cur.append(ln.strip())
        elif cur:
            paras.append(re.sub(r"\s+", " ", " ".join(cur)))
            cur = []
    return paras


def extract_chapter(raw: str) -> Optional[dict]:
    """Plain Gutenberg text -> {title, chapter_title, paragraphs, minutes}; None if no clear first section."""
    raw = raw.replace("\r\n", "\n").lstrip("﻿")
    m = re.search(r"^\*\*\* ?START OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK(.*?)\*\*\*", raw, re.I | re.M)
    head, body = (raw[:m.start()], raw[m.end():]) if m else ("", raw)
    e = re.search(r"^\*\*\* ?END OF (?:THE |THIS )?PROJECT GUTENBERG EBOOK", body, re.I | re.M)
    if e:
        body = body[:e.start()]
    t = re.search(r"^Title:\s*(.+)$", head, re.M) or re.search(r"eBook of (.+)$", head, re.M)
    title = t[1].strip() if t else (_nice(m[1].strip()) if m and m[1].strip() else "")
    lines = body.split("\n")

    def section_end(i: int) -> int:
        for j in range(i + 1, len(lines)):
            if _ANY_HEAD.match(lines[j]) and len(lines[j].strip()) < 60:
                return j
        return len(lines)

    for pat in _FIRST:
        for i, ln in enumerate(lines):
            if not pat.match(ln) or len(ln.strip()) > 60:
                continue
            j = section_end(i)
            # subtitle lines directly under the heading (e.g. "OF THE DIVISION OF LABOUR.")
            k, sub = i + 1, []
            while k < j and lines[k].strip() and lines[k].strip().upper() == lines[k].strip() and len(sub) < 3:
                sub.append(lines[k].strip())
                k += 1
            paras = _paragraphs(lines[k:j])
            text_len = sum(len(p) for p in paras)
            if text_len < 1500:  # a table-of-contents entry or a title page, not the chapter
                continue
            out, n = [], 0
            for p in paras:
                if n + len(p) > MAX_CHARS:
                    if not out:
                        out.append(p[:MAX_CHARS].rsplit(" ", 1)[0] + " ...")
                    break
                out.append(p)
                n += len(p)
            words = sum(len(p.split()) for p in out)
            heading = _nice(" ".join([ln.strip()] + sub))
            return {"title": title, "chapter_title": heading, "paragraphs": out,
                    "minutes": max(1, round(words / 230))}
    return None


def chapter(gutenberg_id: int) -> Optional[dict]:
    """First chapter of Project Gutenberg book `gutenberg_id`, cached on disk; None on any failure."""
    gid = int(gutenberg_id)
    k = f"chapter-{gid}"
    hit = _mem.get(k)
    if hit and time.time() - hit[0] < TTL:
        return hit[1]
    disk = _read_disk(k)
    if disk:
        _mem[k] = (time.time(), disk)
        return disk
    try:
        r = httpx.get(TEXT_URL.format(id=gid), headers={"User-Agent": UA}, timeout=30.0, follow_redirects=True)
        r.raise_for_status()
        r.encoding = "utf-8"
        data = extract_chapter(r.text)
    except Exception:
        return None
    if not data:
        return None
    data["source_url"] = f"https://www.gutenberg.org/ebooks/{gid}"
    _mem[k] = (time.time(), data)
    _write_disk(k, data)
    return data
