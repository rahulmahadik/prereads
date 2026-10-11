"""Resolve a (title, author) to a verified Book.

Order of truth: NLB Catalogue v2 (if keys) -> Open Library -> seed data.
A title that resolves nowhere is dropped by the engine; PreReads never shows a
book that does not exist in a catalogue.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

import httpx

from . import config
from .models import Book, slugify

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
class NLBClient:
    def __init__(self) -> None:
        self.base = config.NLB_BASE
        self.headers = {
            "X-Api-Key": config.NLB_API_KEY,
            "X-App-Code": config.NLB_APP_CODE,
            "Accept": "application/json",
        }

    def enabled(self) -> bool:
        return config.nlb_enabled()

    def _get(self, path: str, **params) -> Optional[dict]:
        """GET with a small backoff on 429 (NLB rate-limits bursts)."""
        if not self.enabled():
            return None
        import time

        for attempt in range(3):
            try:
                r = httpx.get(f"{self.base}/{path}", params=params, headers=self.headers, timeout=config.HTTP_TIMEOUT)
            except Exception as exc:  # noqa: BLE001
                log.warning("NLB %s failed: %s", path, exc)
                return None
            if r.status_code == 429:
                time.sleep(0.8 * (2 ** attempt))
                continue
            if r.status_code == 404:
                return None                      # NLB uses 404 for "no records"
            if r.status_code != 200:
                log.warning("NLB %s -> %s %s", path, r.status_code, r.text[:200])
                return None
            try:
                return r.json()
            except ValueError:
                return None
        return None

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
def openlibrary_search(title: str, author: str = "") -> Optional[Book]:
    if config.effective_demo():
        return None
    params = {"title": title, "limit": 5, "fields": "key,title,author_name,isbn,first_publish_year,number_of_pages_median,subject,cover_i"}
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
        subjects=[str(s) for s in d.get("subject", [])[:15]],
        summary=summary[:3000],
        cover_url=cover,
        source="openlibrary",
    )


def openlibrary_search_many(q: str, page: int = 1, size: int = 20) -> list[Book]:
    """Broad keyword search, paged, for discovery lists (no summary fetch: fast)."""
    if config.effective_demo() or not q.strip():
        return []
    params = {"q": q, "page": page, "limit": size, "fields": "key,title,author_name,isbn,first_publish_year,number_of_pages_median,subject,cover_i"}
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
            pages=d.get("number_of_pages_median"), subjects=[str(x) for x in d.get("subject", [])[:10]],
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
    return _nlb
