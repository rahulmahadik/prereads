"""Resolve a (title, author) to a verified Book.

Order of truth: NLB Catalogue v2 (if keys) -> Open Library -> seed data.
A title that resolves nowhere is dropped by the engine; PreReads never shows a
book that does not exist in a catalogue.

Layer: integrations. resolve() is the single gate every title passes through (services.engine,
services.discover, api/routes_paths). enrich() fills missing metadata from integrations.sources.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from collections import deque
from typing import Any, Callable, Optional

import httpx

from ..core import config
from ..core.models import Book, slugify

log = logging.getLogger("prereads.catalog")


def _pick(obj: dict, *keys: str, default=None):
    """Return the first present key, tolerating camelCase / PascalCase variants."""
    for k in keys:
        for variant in (k, k[:1].lower() + k[1:], k[:1].upper() + k[1:]):
            if variant in obj and obj[variant] not in (None, "", []):
                return obj[variant]
    return default


def _clean_isbn(raw: Any) -> Optional[str]:
    if not raw:
        return None
    if isinstance(raw, list):
        raw = raw[0] if raw else None
        if isinstance(raw, dict):
            raw = _pick(raw, "isbn", "value")
    s = re.sub(r"[^0-9Xx]", "", str(raw or ""))
    if len(s) == 10:
        return s.upper()
    if len(s) == 13:
        return s
    return None


# --------------------------------------------------------------------------- NLB
class RateLimiter:
    """At most `per_second` calls in any second and `per_minute` in any minute, shared by every
    thread. Slots are reserved under the lock, so concurrent callers queue in order.
    `margin` widens both windows: NLB counts when a request arrives, which drifts from when it
    was sent (connection set-up), and a call exactly 1.0 s after the last one got a 429."""

    def __init__(self, per_second: int, per_minute: int, margin: float = 0.0,
                 clock: Callable[[], float] = time.monotonic, sleep: Callable[[float], None] = time.sleep) -> None:
        self.per_second, self.per_minute, self.margin = per_second, per_minute, margin
        self.clock, self.sleep = clock, sleep
        self.slots: deque[float] = deque(maxlen=max(per_second, per_minute))   # reserved send times, ascending
        self.lock = threading.Lock()

    def acquire(self, max_wait: float) -> bool:
        """Wait for a slot and take it; False (taking nothing) when the wait would exceed max_wait."""
        with self.lock:
            now = self.clock()
            at = now
            if len(self.slots) >= self.per_second:
                at = max(at, self.slots[-self.per_second] + 1.0 + self.margin)
            if len(self.slots) >= self.per_minute:
                at = max(at, self.slots[-self.per_minute] + 60.0 + self.margin)
            if at - now > max_wait:
                return False
            self.slots.append(at)
        if at > now:
            self.sleep(at - now)
        return True


# How long each endpoint's answer stays good: shelf status moves quickly, trends daily, records rarely.
_NLB_TTL = {"GetAvailabilityInfo": 15 * 60, "trends": 24 * 3600, "default": 7 * 24 * 3600}


class NLBClient:
    def __init__(self) -> None:
        self.base = config.NLB_BASE
        self.headers = {
            "X-Api-Key": config.NLB_API_KEY,
            "X-App-Code": config.NLB_APP_CODE,
            "Accept": "application/json",
        }
        self.limiter = RateLimiter(config.NLB_RATE_PER_SECOND, config.NLB_RATE_PER_MINUTE, margin=0.5)
        self.cooldown_until = 0.0      # set by a 429: no calls at all until then
        self._mem: dict[str, tuple[float, Optional[dict]]] = {}
        self._http: Optional[httpx.Client] = None   # one kept-alive connection: steadier timing, faster calls

    def _send(self, path: str, params: dict) -> httpx.Response:
        if self._http is None:
            self._http = httpx.Client(headers=self.headers, timeout=config.HTTP_TIMEOUT)
        return self._http.get(f"{self.base}/{path}", params=params)

    def enabled(self) -> bool:
        return config.nlb_enabled()

    @staticmethod
    def _ttl(path: str) -> int:
        if path == config.NLB_TRENDS_PATH:
            return _NLB_TTL["trends"]
        return _NLB_TTL.get(path, _NLB_TTL["default"])

    def _cached(self, key: str, path: str) -> tuple[bool, Optional[dict]]:
        """(hit, data) from memory, then disk. A cached None means NLB had no records."""
        now = time.time()
        if key in self._mem and now - self._mem[key][0] < self._ttl(path):
            return True, self._mem[key][1]
        f = config.NLB_CACHE_DIR / f"{key}.json"
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, None
        if now - rec.get("t", 0) >= self._ttl(path):
            return False, None
        self._mem[key] = (rec["t"], rec.get("data"))
        return True, rec.get("data")

    def _store(self, key: str, path: str, data: Optional[dict]) -> None:
        t = time.time()
        self._mem[key] = (t, data)
        try:
            config.NLB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
            (config.NLB_CACHE_DIR / f"{key}.json").write_text(json.dumps({"t": t, "path": path, "data": data}), encoding="utf-8")
        except OSError as exc:
            log.warning("NLB cache write failed: %s", exc)

    def _get(self, path: str, **params) -> Optional[dict]:
        """Cached GET within NLB's rate limits. Never retries: a retry spends the same small budget.
        None for "no records" (cached) and for any failure or skipped call (not cached)."""
        if not self.enabled():
            return None
        key = hashlib.sha1(json.dumps([path, sorted(params.items())], default=str).encode()).hexdigest()
        hit, data = self._cached(key, path)
        if hit:
            return data
        pause = self.cooldown_until - time.monotonic()
        if pause > config.NLB_MAX_WAIT:
            return None
        if pause > 0:
            time.sleep(pause)                    # a short 429 pause (Retry-After: 1) is waited out
        if not self.limiter.acquire(config.NLB_MAX_WAIT):
            log.info("NLB %s skipped: over %s/min, falling back", path, config.NLB_RATE_PER_MINUTE)
            return None
        try:
            r = self._send(path, params)
        except Exception as exc:  # noqa: BLE001
            log.warning("NLB %s failed: %s", path, exc)
            return None
        if r.status_code == 429:
            try:
                wait = float(r.headers.get("Retry-After", 60))
            except ValueError:
                wait = 60.0
            self.cooldown_until = time.monotonic() + wait
            log.warning("NLB rate limit hit; pausing NLB calls for %.0f s", wait)
            return None
        if r.status_code == 404:
            self._store(key, path, None)         # NLB uses 404 for "no records"
            return None
        if r.status_code != 200:
            log.warning("NLB %s -> %s %s", path, r.status_code, r.text[:200])
            return None
        try:
            data = r.json()
        except ValueError:
            return None
        self._store(key, path, data)
        return data

    def search(self, title: str, author: str = "", limit: int = 5) -> list[dict]:
        """GetTitles ANDs Title/Author/ISBN/Subject/Keywords; SearchTitles is free text."""
        params = {"Title": title, "Limit": limit}
        if author:
            params["Author"] = author.split(",")[0].split(" ")[-1]   # surname is the robust token
        data = self._get("GetTitles", **params)
        titles = (_pick(data, "titles", default=[]) if data else []) or []
        if not titles:
            data = self._get("SearchTitles", Keywords=f"{title} {author}".strip(), Limit=limit)
            titles = (_pick(data, "titles", default=[]) if data else []) or []
        return titles if isinstance(titles, list) else []

    def search_isbn(self, isbn: str) -> list[dict]:
        data = self._get("GetTitles", ISBN=isbn, Limit=3)
        titles = (_pick(data, "titles", default=[]) if data else []) or []
        return titles if isinstance(titles, list) else []

    def details(self, brn: Optional[str] = None, isbn: Optional[str] = None) -> Optional[dict]:
        params = {}
        if brn:
            params["BRN"] = brn
        elif isbn:
            params["ISBN"] = isbn
        else:
            return None
        return self._get("GetTitleDetails", **params)

    def availability(self, brn: Optional[str] = None, isbn: Optional[str] = None) -> list[dict]:
        params = {"Limit": 100}
        if brn:
            params["BRN"] = brn
        elif isbn:
            params["ISBN"] = isbn
        else:
            return []
        data = self._get("GetAvailabilityInfo", **params)
        if not data:
            return []
        items = _pick(data, "items", default=[]) or []
        return items if isinstance(items, list) else []

    def trends(self, location: Optional[str] = None, limit: int = 50) -> list[dict]:
        """GetMostCheckoutsTrendsTitles?LocationCode=BIPL&Duration=past30days ->
        {checkoutsTrends:[{language, ageLevel, fiction, checkoutsTitles:[{title, author, isbns, checkoutsCount}]}]}.
        Flattened to the title rows."""
        if not location:
            return []
        data = self._get(config.NLB_TRENDS_PATH, LocationCode=location, Duration=config.NLB_TRENDS_DURATION)
        if not data:
            return []
        groups = _pick(data, "checkoutsTrends", default=[]) or []
        rows: list[dict] = []
        for g in groups if isinstance(groups, list) else []:
            for t in (_pick(g, "checkoutsTitles", default=[]) or []):
                if isinstance(t, dict):
                    rows.append({**t, "fiction": g.get("fiction"), "ageLevel": g.get("ageLevel"), "language": g.get("language")})
        return rows[:limit] if limit else rows

    @staticmethod
    def to_book(item: dict) -> Book:
        """A TitleSummary ({title, author, coverUrl, records:[TitleRecord]}) or a flat
        Title/GetTitleDetails object. Record-level fields live in records[0]."""
        rec = item
        records = _pick(item, "records", default=None)
        if isinstance(records, list) and records and isinstance(records[0], dict):
            # Prefer the record with physical copies, else the first.
            rec = next((r for r in records if r.get("availability")), records[0])
        title = str(_pick(item, "title", default=_pick(rec, "title", default="")) or "").split(" / ")[0].strip()
        author = str(_pick(item, "author", default=_pick(rec, "author", default="")) or "").strip().rstrip(",.")
        isbns = _pick(rec, "isbns", default=[]) or []
        isbn = next((_clean_isbn(i) for i in isbns if _clean_isbn(i) and len(_clean_isbn(i)) == 13), None) or (_clean_isbn(isbns[0]) if isbns else None)
        brn = _pick(rec, "brn")
        year = _pick(rec, "publishDate", "publishYear")
        try:
            year = int(re.search(r"(1[5-9]|20)\d{2}", str(year)).group(0)) if year else None
        except (AttributeError, ValueError):
            year = None
        subjects = _pick(rec, "subjects", default=[]) or []
        if isinstance(subjects, str):
            subjects = [subjects]
        summary = _pick(rec, "summary", default="") or ""
        if isinstance(summary, list):
            summary = " ".join(str(x) for x in summary)
        pages = None
        for pd in (_pick(rec, "physicalDescription", default=[]) or []):
            m = re.search(r"(\d{2,4})\s*(p\.|pages)", str(pd))
            if m:
                pages = int(m.group(1))
                break
        cover = _pick(item, "coverUrl", default=None)
        if isinstance(cover, dict):
            cover = _pick(cover, "medium", "small", "large")
        audience = _pick(rec, "audience", default=[]) or []
        return Book(
            id=isbn or f"ol:{slugify(title, author)}",
            title=title,
            author=author,
            isbn=isbn,
            brn=str(brn) if brn else None,
            year=year,
            pages=pages,
            subjects=[str(s) for s in subjects][:15],
            summary=str(summary)[:3000],
            cover_url=cover if isinstance(cover, str) else None,
            reservations=int(_pick(rec, "activeReservationsCount", default=0) or 0),
            audience=[str(a) for a in audience] if isinstance(audience, list) else [],
            source="nlb",
        )


# ------------------------------------------------------------------ Open Library
def pick_ddc(values) -> Optional[str]:
    """Representative Dewey class: most common 3-digit prefix, then the shortest value with it."""
    vals = [str(v).strip() for v in (values or []) if re.match(r"^\d{3}(\.\d+)?$", str(v).strip())]
    if not vals:
        return None
    counts: dict[str, int] = {}
    for v in vals:
        counts[v[:3]] = counts.get(v[:3], 0) + 1
    best = max(counts.values())
    prefix = next(v[:3] for v in vals if counts[v[:3]] == best)  # ties: first seen
    return min((v for v in vals if v.startswith(prefix)), key=len)


def openlibrary_ddc(title: str, author: str = "") -> Optional[str]:
    """Real Dewey class for a title via Open Library (no key). None when unknown or on error."""
    params = {"title": title, "limit": 5, "fields": "title,author_name,ddc"}
    if author:
        params["author"] = author
    try:
        r = httpx.get(f"{config.OPENLIBRARY_BASE}/search.json", params=params, timeout=config.HTTP_TIMEOUT,
                      headers={"User-Agent": "PreReads makeathon prototype"})
        r.raise_for_status()
        docs = r.json().get("docs", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Open Library ddc lookup failed: %s", exc)
        return None
    for d in docs:
        if title_matches(title, str(d.get("title", ""))) and d.get("ddc"):
            return pick_ddc(d["ddc"])
    return None


def openlibrary_search(title: str, author: str = "") -> Optional[Book]:
    """Best Open Library match whose title passes title_matches(), or None (also in demo mode)."""
    if config.effective_demo():
        return None
    params = {"title": title, "limit": 5, "fields": "key,title,author_name,isbn,first_publish_year,number_of_pages_median,subject,cover_i,ddc"}
    if author:
        params["author"] = author
    try:
        r = httpx.get(f"{config.OPENLIBRARY_BASE}/search.json", params=params, timeout=config.HTTP_TIMEOUT,
                      headers={"User-Agent": "PreReads-makeathon/0.1 (contact: team)"})
        r.raise_for_status()
        docs = r.json().get("docs", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Open Library search failed: %s", exc)
        return None
    docs = [d for d in docs if title_matches(title, str(d.get("title", "")))]
    if not docs:
        return None
    d = docs[0]
    isbns = [i for i in d.get("isbn", []) if len(i) == 13] or d.get("isbn", [])
    isbn = _clean_isbn(isbns[0]) if isbns else None
    cover = f"https://covers.openlibrary.org/b/id/{d['cover_i']}-M.jpg" if d.get("cover_i") else None
    summary = ""
    key = d.get("key")
    if key:
        try:
            w = httpx.get(f"{config.OPENLIBRARY_BASE}{key}.json", timeout=config.HTTP_TIMEOUT).json()
            desc = w.get("description", "")
            summary = desc.get("value", "") if isinstance(desc, dict) else str(desc or "")
        except Exception:  # noqa: BLE001
            pass
    t = str(d.get("title", title))
    a = ", ".join(d.get("author_name", [])[:2]) or author
    return Book(
        id=isbn or f"ol:{slugify(t, a)}",
        title=t,
        author=a,
        isbn=isbn,
        year=d.get("first_publish_year"),
        pages=d.get("number_of_pages_median"),
        ddc=pick_ddc(d.get("ddc")),
        subjects=[str(s) for s in d.get("subject", [])[:15]],
        summary=summary[:3000],
        cover_url=cover,
        source="openlibrary",
    )


def openlibrary_search_many(q: str, page: int = 1, size: int = 20) -> list[Book]:
    """Broad keyword search, paged, for discovery lists (no summary fetch: fast)."""
    if config.effective_demo() or not q.strip():
        return []
    params = {"q": q, "page": page, "limit": size, "fields": "key,title,author_name,isbn,first_publish_year,number_of_pages_median,subject,cover_i,ddc"}
    try:
        r = httpx.get(f"{config.OPENLIBRARY_BASE}/search.json", params=params, timeout=config.HTTP_TIMEOUT,
                      headers={"User-Agent": "PreReads-makeathon/0.1 (contact: team)"})
        r.raise_for_status()
        docs = r.json().get("docs", [])
    except Exception as exc:  # noqa: BLE001
        log.warning("Open Library search failed: %s", exc)
        return []
    out: list[Book] = []
    for d in docs:
        isbns = [i for i in d.get("isbn", []) if len(i) == 13] or d.get("isbn", [])
        isbn = _clean_isbn(isbns[0]) if isbns else None
        t = str(d.get("title", "")).strip()
        a = ", ".join(d.get("author_name", [])[:2])
        if not t:
            continue
        out.append(Book(
            id=isbn or f"ol:{slugify(t, a)}", title=t, author=a, isbn=isbn, year=d.get("first_publish_year"),
            pages=d.get("number_of_pages_median"), ddc=pick_ddc(d.get("ddc")), subjects=[str(x) for x in d.get("subject", [])[:10]],
            cover_url=f"https://covers.openlibrary.org/b/id/{d['cover_i']}-M.jpg" if d.get("cover_i") else None, source="openlibrary",
        ))
    return out


# ---------------------------------------------------------------------- resolve
_nlb = NLBClient()

_STOP = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "with"}


def _tokens(s: str) -> set[str]:
    return {t for t in re.sub(r"[^a-z0-9 ]", " ", s.lower()).split() if t not in _STOP and len(t) > 1}


def title_matches(wanted: str, got: str) -> bool:
    """Guard against fuzzy catalogue hits returning a different book."""
    w, g = _tokens(wanted), _tokens(got)
    if not w or not g:
        return False
    overlap = len(w & g) / len(w)
    return overlap >= 0.6


def resolve(title: str, author: str = "", seed: Optional[dict] = None) -> Optional[Book]:
    """Verify a title exists. Returns the richest Book we can build, or None."""
    book: Optional[Book] = None
    if _nlb.enabled():
        hits = []
        if seed and seed.get("isbn"):
            hits = _nlb.search_isbn(seed["isbn"])
        if not hits:
            hits = _nlb.search(title, author)
        hits = [h for h in hits if title_matches(title, str(_pick(h, "title", "titleName", default="")))]
        if hits:
            book = NLBClient.to_book(hits[0])
            if not book.summary or not book.subjects:
                det = _nlb.details(brn=book.brn, isbn=book.isbn)
                if isinstance(det, dict):
                    full = NLBClient.to_book(det)
                    book.summary = book.summary or full.summary
                    book.subjects = book.subjects or full.subjects
                    book.pages = book.pages or full.pages
                    book.reservations = book.reservations or full.reservations
    if book is None:
        book = openlibrary_search(title, author)
    if book is None and seed:
        book = Book(
            id=seed.get("isbn") or f"ol:{slugify(seed['title'], seed.get('author', ''))}",
            title=seed["title"],
            author=seed.get("author", ""),
            isbn=seed.get("isbn"),
            year=seed.get("year"),
            pages=seed.get("pages"),
            subjects=seed.get("subjects", []),
            summary=seed.get("summary", ""),
            source="seed",
        )
    # Seed data can enrich a thin catalogue hit.
    if book and seed:
        book.pages = book.pages or seed.get("pages")
        book.year = book.year or seed.get("year")
        if not book.subjects:
            book.subjects = seed.get("subjects", [])
        if not book.summary:
            book.summary = seed.get("summary", "")
    return book


def nlb() -> NLBClient:
    """The shared NLB client. Callers check .enabled() (keys present and NLB switched on)."""
    return _nlb


# ----------------------------------------------------------------------- enrich
ENRICH_DIR = config.CACHE_DIR / "enrich"
ENRICH_TTL = 30 * 24 * 3600
ENRICH_FIELDS = ("summary", "subjects", "pages", "cover_url", "ddc", "audience", "year")


def _enrich_path(book_id: str):
    return ENRICH_DIR / f"{re.sub(r'[^A-Za-z0-9_-]+', '_', book_id)[:120]}.json"


def _enrich_cache_read(book_id: str) -> dict:
    if not book_id:
        return {}
    try:
        p = _enrich_path(book_id)
        if p.exists():
            d = json.loads(p.read_text(encoding="utf-8"))
            if time.time() - float(d.get("ts", 0)) < ENRICH_TTL and isinstance(d.get("sources"), dict):
                return d["sources"]
    except Exception:  # noqa: BLE001
        pass
    return {}


def _enrich_cache_write(book: Book, recs: dict) -> None:
    if not book.id:
        return
    try:
        ENRICH_DIR.mkdir(parents=True, exist_ok=True)
        _enrich_path(book.id).write_text(json.dumps(
            {"ts": time.time(), "id": book.id, "title": book.title, "author": book.author, "sources": recs},
            indent=1, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _empty(v) -> bool:
    return v is None or v == "" or v == []


def _valid(field: str, v):
    """The value in Book's type, or None when it does not fit."""
    if field in ("subjects", "audience"):
        vals = [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []
        return vals[:15] or None
    if field == "pages":
        return int(v) if isinstance(v, (int, float)) and 10 <= int(v) <= 5000 else None
    if field == "year":
        return int(v) if isinstance(v, (int, float)) and 1400 <= int(v) <= time.gmtime().tm_year + 1 else None
    if field in ("summary", "cover_url", "ddc"):
        return str(v).strip() or None if isinstance(v, str) else None
    return None


def enrich(book: Book, network: Optional[bool] = None) -> Book:
    """Fill ONLY the missing summary, subjects, pages, cover_url, ddc, audience and year from open
    sources, first source with a value wins (merge order: sources.ORDER). A field that already has
    a value (NLB, Open Library or seed) is never touched; book.field_sources records who filled what.

    Per-source records are cached in data/cache/enrich/<book id>.json; failures are not cached.
    6 s budget per source. DEMO mode reads the cache only (network=True/False overrides).
    Never raises: on any error the book comes back unchanged."""
    try:
        from . import sources  # local import: sources imports catalog

        missing = [f for f in ENRICH_FIELDS if _empty(getattr(book, f))]
        if not missing or not book.title:
            return book
        allow_net = (not config.effective_demo()) if network is None else bool(network)
        recs = _enrich_cache_read(book.id)
        failed: set[str] = set()
        fetched = False
        out = book.model_copy(deep=True)
        for field in missing:
            for src in sources.ORDER.get(field, ()):
                if src not in recs:
                    if not allow_net or src in failed or src not in sources.FETCHERS:
                        continue
                    try:
                        recs[src] = sources.FETCHERS[src](book.title, book.author, book.isbn) or {}
                        fetched = True
                    except Exception as exc:  # noqa: BLE001  (SourceError or anything unexpected)
                        log.info("enrich %s via %s failed: %s", book.id, src, exc)
                        failed.add(src)
                        continue
                rec = recs.get(src)
                val = _valid(field, rec.get(field)) if isinstance(rec, dict) and field in rec else None
                if val is not None:
                    setattr(out, field, val)
                    out.field_sources = {**out.field_sources, field: src}
                    break
        if fetched:
            _enrich_cache_write(book, recs)
        return out
    except Exception as exc:  # noqa: BLE001
        log.warning("enrich %s failed: %s", getattr(book, "id", "?"), exc)
        return book
