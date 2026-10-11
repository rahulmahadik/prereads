"""Backfill real Dewey classes (Open Library) into cached routes.

    python scripts/backfill_ddc.py [--dry-run]

For every stop in data/cache/routes/*.json: look up ddc by title + author, set
book.ddc, and rewrite call_number on demo availability rows only. Run only when
no precompute process is writing the same files (pgrep -f precompute.py).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations import catalog  # noqa: E402
from app.integrations.availability import _author_code  # noqa: E402
from app.core.models import Book  # noqa: E402

ROUTES = Path(__file__).resolve().parent.parent / "data" / "cache" / "routes"
_memo: dict[tuple[str, str], str | None] = {}


def lookup(title: str, author: str) -> str | None:
    key = (title.lower().strip(), author.lower().strip())
    if key not in _memo:
        _memo[key] = catalog.openlibrary_ddc(title, author)
        time.sleep(0.5)  # one request at a time, gently
    return _memo[key]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    stops_total = stops_hit = 0
    for f in sorted(ROUTES.glob("*.json")):
        data = json.loads(f.read_text())
        changed = False
        for stop in data.get("stops", []):
            b = stop.get("book") or {}
            if not b.get("title"):
                continue
            stops_total += 1
            ddc = lookup(b["title"], b.get("author", ""))
            if not ddc:
                continue
            stops_hit += 1
            if b.get("ddc") != ddc:
                b["ddc"] = ddc
                changed = True
            code = _author_code(Book(id=b.get("id", ""), title=b["title"], author=b.get("author", "")))
            for row in stop.get("availability") or []:
                if row.get("demo"):
                    new = f"English {ddc} {code}"
                    if row.get("call_number") != new:
                        row["call_number"] = new
                        changed = True
        if changed and not args.dry_run:
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    print(f"stops: {stops_total}, with real ddc: {stops_hit}, distinct lookups: {len(_memo)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
