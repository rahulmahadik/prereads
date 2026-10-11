"""Check the NLB Catalogue v2 API with real keys.

    cd backend && . .venv/bin/activate && python scripts/nlb_check.py "Thinking, Fast and Slow"

Prints what each Catalogue v2 endpoint returns for one title so you can see the
real field names before trusting the cache. Needs NLB_API_KEY and NLB_APP_CODE
in .env (DEMO=0).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core import config  # noqa: E402
from app.integrations.catalog import NLBClient, _pick  # noqa: E402


def main() -> int:
    if {"-h", "--help"} & set(sys.argv[1:]):
        print(__doc__)
        return 0
    if not config.nlb_enabled():
        print("NLB keys missing or DEMO=1. Put NLB_API_KEY and NLB_APP_CODE in .env and set DEMO=0.")
        return 1
    title = " ".join(sys.argv[1:]) or "Thinking, Fast and Slow"
    c = NLBClient()
    print(f"\n== GetTitles / SearchTitles: {title!r}")
    hits = c.search(title)
    print(f"{len(hits)} hits")
    if not hits:
        return 1
    print(json.dumps(hits[0], indent=2)[:1500])
    book = NLBClient.to_book(hits[0])
    print(f"\nparsed -> id={book.id} brn={book.brn} isbn={book.isbn} pages={book.pages} year={book.year} reservations={book.reservations}")
    print(f"\n== GetTitleDetails brn={book.brn}")
    det = c.details(brn=book.brn, isbn=book.isbn)
    print(json.dumps(det, indent=2)[:1200] if det else "none")
    print(f"\n== GetAvailabilityInfo brn={book.brn}")
    items = c.availability(brn=book.brn, isbn=book.isbn)
    print(f"{len(items)} items")
    for it in items[:6]:
        loc = _pick(it, "location", default={}) or {}
        st = _pick(it, "status", default={}) or {}
        print(f"  {loc.get('code'):6} {loc.get('name'):32} {_pick(it, 'formattedCallNumber', 'callNumber', default=''):26} {st.get('name')}")
    print("\n== GetMostCheckoutsTrendsTitles LocationCode=BIPL")
    rows = c.trends(location="BIPL", limit=5)
    for r in rows:
        print(f"  {r.get('checkoutsCount'):>4}  {str(r.get('title'))[:50]:50} {r.get('ageLevel')} {r.get('language')}")
    print("\nIf the shapes above look right, run: python scripts/precompute.py --refresh")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
