"""Open book-metadata sources used by catalog.enrich() to fill gaps (no keys needed).

Each fetcher returns a small normalized dict of the fields it found, ``{}`` when the
source has no matching record, or raises ``SourceError`` on a network / HTTP failure
(failures are not cached, empty results are). Measured coverage and terms of use:
internal/BOOK_DATA_SOURCES.md.

  overdrive    NLB's OverDrive (Libby) catalogue, thunder API, library key "nlb": real NLB
               digital-collection records. description, subjects, cover, audience.
  openlibrary  search.json + /works/<key>.json. ddc, pages, first publish year, subjects,
               cover, description.
  google       Google Books volumes without a key. Rate-limited (429) per IP; last resort.

Layer: integrations. Only catalog.enrich() calls these (and scripts/enrich_books.py through it).
"""
from __future__ import annotations

import html
import re
import time
import unicodedata
from typing import Any, Optional

import httpx

from .catalog import pick_ddc

UA = {"User-Agent": "PreReads makeathon prototype", "Accept": "application/json"}
TIMEOUT = 6.0                      # seconds, per source (all of its requests together)

OVERDRIVE = "https://thunder.api.overdrive.com/v2/libraries/nlb/media"
OPENLIBRARY = "https://openlibrary.org"
GOOGLE = "https://www.googleapis.com/books/v1/volumes"

# Words that mark a different book sharing the title: adaptations, summaries, study aids.
_OTHER_BOOK = {"young", "kids", "children", "childrens", "readers", "adapted", "junior", "graphic",
               "summary", "workbook", "analysis", "guide", "study", "abridged", "illustrated"}


class SourceError(Exception):
    """Network or HTTP failure: the caller skips this source and does not cache it."""


COOLDOWN = 120.0                   # after a 429, leave that host alone this long
_cool_until: dict[str, float] = {}


def _host(url: str) -> str:
    return url.split("/")[2] if "//" in url else url


def _get(url: str, params: Optional[dict] = None, deadline: Optional[float] = None, retry_429: bool = False) -> Any:
    deadline = deadline or (time.monotonic() + TIMEOUT)
    if _cool_until.get(_host(url), 0) > time.monotonic():
        raise SourceError("rate-limited earlier; cooling down")
    for attempt in range(2 if retry_429 else 1):
        left = deadline - time.monotonic()
        if left <= 0.2:
            raise SourceError("timeout budget used")
        try:
            r = httpx.get(url, params=params, headers=UA, timeout=left, follow_redirects=True)
        except Exception as exc:  # noqa: BLE001
            raise SourceError(f"{type(exc).__name__}: {exc}") from exc
        if r.status_code == 429 and retry_429 and attempt == 0 and deadline - time.monotonic() > 2.5:
            time.sleep(1.5)
            continue
        if r.status_code == 429:
            _cool_until[_host(url)] = time.monotonic() + COOLDOWN
            raise SourceError("HTTP 429")
        if r.status_code == 404:
            return None
        if r.status_code != 200:
            raise SourceError(f"HTTP {r.status_code}")
        try:
            return r.json()
        except ValueError as exc:
            raise SourceError("bad json") from exc
    raise SourceError("HTTP 429")


_STOPW = {"the", "a", "an", "of", "and", "to", "in", "on", "for", "with"}


def _words(s: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", s.lower()))


def _tok(s: str) -> set[str]:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"\b[a-z0-9]+\s+edition\b", " ", s)          # "Second Edition", "3rd edition"
    return {t for t in re.findall(r"[a-z0-9]+", s) if t not in _STOPW and len(t) > 1}


def _close(a: str, b: str) -> bool:
    """Same token set; titles of 4+ words may differ by one word in five (Jaccard >= 0.8)."""
    A, B = _tok(a), _tok(b)
    if not A or not B:
        return False
    if A == B:
        return True
    return min(len(A), len(B)) >= 4 and len(A & B) / len(A | B) >= 0.8


def _main(t: str) -> str:
    return re.split(r"\s*[:(]", t, maxsplit=1)[0]


def same_title(wanted: str, got: str) -> bool:
    """Stricter than title_matches: subtitles may differ, but an adaptation or a summary of
    the book ("... for Young People", "Summary of ..."), or a near-namesake ("Why We Can't
    Sleep" for "Why We Sleep"), is a different book."""
    if not wanted or not got:
        return False
    if (_words(got) & _OTHER_BOOK) - _words(wanted):
        return False
    return _close(wanted, got) or _close(_main(wanted), _main(got))


def _surname(author: str) -> str:
    """'Daniel Kahneman' / 'Kahneman, Daniel' / 'Gene Kim, Kevin Behr' -> the first author's surname."""
    first = re.split(r";| and | & ", author or "")[0].split(",")[0]
    toks = re.findall(r"[a-zà-ÿ]+", first.lower())
    return toks[-1] if toks else ""


def _first_author(author: str) -> str:
    return re.split(r";| and | & |,", author or "")[0].strip()


def _author_ok(author: str, names: str) -> bool:
    sur = _surname(author)
    return not sur or sur in names.lower()


def strip_html(s: str) -> str:
    s = re.sub(r"<\s*(br|/p|/li)\s*/?>", " ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def _year(v: Any) -> Optional[int]:
    m = re.search(r"(1[5-9]|20)\d{2}", str(v or ""))
    return int(m.group(0)) if m else None


# ------------------------------------------------------------------ OverDrive (NLB)
def overdrive_audience(item: dict) -> list[str]:
    """Audience from OverDrive's own collection flags and subjects. "General content" is a
    maturity rating, not an audience; an adult-collection title has neither juvenile nor
    young-adult subjects or flags."""
    subs = " | ".join(str(s.get("name", "")) for s in item.get("subjects") or [] if isinstance(s, dict)).lower()
    if "juvenile" in subs:
        return ["Children"]
    if "young adult" in subs:
        return ["Young adult"]
    if item.get("juvenileEligible") and not item.get("youngAdultEligible"):
        return ["Children"]
    if item.get("youngAdultEligible"):
        return ["Young adult"]
    # Sitting in the adult collection is not an audience signal (beginner books live there
    # too), so leave it empty and let the reading-age estimate speak.
    return []


def overdrive(title: str, author: str, isbn: Optional[str] = None) -> dict:
    data = _get(OVERDRIVE, {"query": f"{_main(title)} {_surname(author)}".strip(), "perPage": 10})
    items = (data or {}).get("items") or []
    best = None
    for it in items:
        isbns = {idf.get("value") for fm in it.get("formats") or [] for idf in fm.get("identifiers") or []}
        creators = " ".join(str(c.get("name", "")) for c in it.get("creators") or [])
        if isbn and isbn in isbns:
            best = it
            break
        if same_title(title, str(it.get("title", ""))) and _author_ok(author, creators):
            # Prefer the eBook record (portrait cover) over the audiobook.
            if best is None or ((it.get("type") or {}).get("id") == "ebook" and (best.get("type") or {}).get("id") != "ebook"):
                best = it
    if best is None:
        return {}
    out: dict[str, Any] = {"ref": best.get("reserveId") or best.get("id")}
    desc = strip_html(str(best.get("description") or ""))
    if len(desc) > 40:
        out["summary"] = desc[:3000]
    subs = [str(s.get("name")) for s in best.get("subjects") or [] if isinstance(s, dict) and s.get("name")]
    subs += [str(b.get("description")) for b in best.get("bisac") or [] if isinstance(b, dict) and b.get("description")]
    if subs:
        out["subjects"] = list(dict.fromkeys(subs))[:15]
    covers = best.get("covers") or {}
    for size in ("cover300Wide", "cover510Wide", "cover150Wide"):
        c = covers.get(size) or {}
        if c.get("href") and not c.get("isPlaceholderImage"):
            out["cover_url"] = c["href"]
            break
    aud = overdrive_audience(best)
    if aud:
        out["audience"] = aud
    y = _year(best.get("publishDate"))
    if y:
        out["year_edition"] = y      # the digital edition's date, not first publication
    return out


# --------------------------------------------------------------------- Open Library
_OL_FIELDS = "key,title,author_name,isbn,ddc,number_of_pages_median,subject,cover_i,first_publish_year"


def openlibrary(title: str, author: str, isbn: Optional[str] = None) -> dict:
    deadline = time.monotonic() + TIMEOUT
    docs: list[dict] = []
    if isbn:
        d = _get(f"{OPENLIBRARY}/search.json", {"q": f"isbn:{isbn}", "fields": _OL_FIELDS, "limit": 3}, deadline)
        docs = [x for x in (d or {}).get("docs", []) if same_title(title, str(x.get("title", "")))]
    if not docs:
        params = {"title": _main(title), "fields": _OL_FIELDS, "limit": 5}
        if author:
            params["author"] = _first_author(author)
        d = _get(f"{OPENLIBRARY}/search.json", params, deadline)
        docs = [x for x in (d or {}).get("docs", []) if same_title(title, str(x.get("title", "")))
                and _author_ok(author, " ".join(x.get("author_name") or []))]
    if not docs:
        return {}
    x = docs[0]
    out: dict[str, Any] = {"ref": x.get("key")}
    if x.get("ddc") and pick_ddc(x["ddc"]):
        out["ddc"] = pick_ddc(x["ddc"])
    if x.get("number_of_pages_median"):
        out["pages"] = int(x["number_of_pages_median"])
    if x.get("first_publish_year"):
        out["year"] = int(x["first_publish_year"])
    if x.get("subject"):
        out["subjects"] = [str(s) for s in x["subject"][:15]]
        low = " | ".join(out["subjects"]).lower()
        if "juvenile" in low:
            out["audience"] = ["Children"]
        elif "young adult" in low:
            out["audience"] = ["Young adult"]
    if x.get("cover_i"):
        out["cover_url"] = f"https://covers.openlibrary.org/b/id/{x['cover_i']}-M.jpg"
    if x.get("key"):
        try:
            w = _get(f"{OPENLIBRARY}{x['key']}.json", None, deadline) or {}
            desc = w.get("description", "")
            desc = desc.get("value", "") if isinstance(desc, dict) else str(desc or "")
            desc = re.split(r"\n\s*(-{3,}|\*\*\*|\(\[source\])", desc)[0].strip()
            if len(desc) > 40:
                out["summary"] = desc[:3000]
        except SourceError:
            pass                       # the search hit is still useful without the description
    return out


# ---------------------------------------------------------------------- Google Books
def google(title: str, author: str, isbn: Optional[str] = None) -> dict:
    deadline = time.monotonic() + TIMEOUT
    if isbn:
        q = f"isbn:{isbn}"
    else:
        q = f'intitle:"{_main(title)}"' + (f" inauthor:{_surname(author)}" if _surname(author) else "")
    d = _get(GOOGLE, {"q": q, "maxResults": 5, "printType": "books"}, deadline, retry_429=True)
    best = None
    for it in (d or {}).get("items") or []:
        v = it.get("volumeInfo") or {}
        if same_title(title, f"{v.get('title', '')}") and _author_ok(author, " ".join(v.get("authors") or [])):
            best = v
            break
    if best is None:
        return {}
    out: dict[str, Any] = {}
    desc = strip_html(str(best.get("description") or ""))
    if len(desc) > 40:
        out["summary"] = desc[:3000]
    if best.get("categories"):
        out["subjects"] = [str(c) for c in best["categories"]][:15]
    if best.get("pageCount"):
        out["pages"] = int(best["pageCount"])
    img = (best.get("imageLinks") or {})
    link = img.get("thumbnail") or img.get("smallThumbnail")
    if link:
        out["cover_url"] = str(link).replace("http://", "https://")
    if best.get("maturityRating") == "MATURE":
        out["audience"] = ["Adult"]
    y = _year(best.get("publishedDate"))
    if y:
        out["year"] = y
    return out


FETCHERS = {"overdrive": overdrive, "openlibrary": openlibrary, "google": google}

# Merge order per field (first source with a value wins). Book fields only; never NLB data.
ORDER: dict[str, tuple[str, ...]] = {
    "summary": ("overdrive", "openlibrary", "google"),
    "subjects": ("openlibrary", "overdrive", "google"),
    "pages": ("openlibrary", "google"),
    "cover_url": ("overdrive", "openlibrary", "google"),
    "ddc": ("openlibrary",),
    "audience": ("overdrive", "openlibrary", "google"),
    "year": ("openlibrary", "google"),
}
