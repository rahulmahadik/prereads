"""Fill missing book fields in the cached routes from open sources (catalog.enrich).

    python scripts/enrich_books.py [--dry-run] [--offline]

For every stop in data/cache/routes/*.json: run catalog.enrich on the book (fills only empty
summary / subjects / pages / cover_url / ddc / audience / year, records book.field_sources),
rewrite the route JSON in place (same shape) and print before/after coverage per field.
--dry-run computes coverage (and warms data/cache/enrich) without writing routes;
--offline uses the enrich cache only. Refuses to write while precompute.py is running.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import catalog  # noqa: E402
from app.models import Book  # noqa: E402

ROUTES = Path(__file__).resolve().parent.parent / "data" / "cache" / "routes"
FIELDS = catalog.ENRICH_FIELDS


def precompute_running() -> bool:
    try:
        r = subprocess.run(["pgrep", "-f", "scripts/precompute.py"], capture_output=True, text=True, timeout=5)
        return bool(r.stdout.strip())
    except Exception:  # noqa: BLE001
        return False


def coverage(books: list[dict]) -> dict[str, int]:
    return {f: sum(1 for b in books if not catalog._empty(b.get(f))) for f in FIELDS}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="do not rewrite route files")
    ap.add_argument("--offline", action="store_true", help="enrich cache only, no network")
    ap.add_argument("--force", action="store_true", help="write even if precompute.py is running")
    args = ap.parse_args()
    if not args.dry_run and not args.force and precompute_running():
        print("precompute.py is running and writes the same files; re-run when it finishes (or use --dry-run).")
        return 2

    files = sorted(ROUTES.glob("*.json"))
    before: list[dict] = []
    after: list[dict] = []
    seen: set[str] = set()
    by_source: dict[str, int] = {}
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        changed = False
        for stop in data.get("stops", []):
            b = stop.get("book") or {}
            if not b.get("title"):
                continue
            before.append(dict(b))
            seen.add(b.get("id") or b["title"])
            # Per stop, not per id: two routes can hold different copies of the same book.
            # Repeat calls are served from data/cache/enrich.
            cache = catalog._enrich_path(b.get("id", ""))
            mtime = cache.stat().st_mtime if cache.exists() else None
            new = catalog.enrich(Book(**b), network=not args.offline).model_dump()
            if not args.offline and (cache.stat().st_mtime if cache.exists() else None) != mtime:
                time.sleep(0.4)  # fetched from the network: be gentle, one book at a time
            for field in FIELDS:
                src = new["field_sources"].get(field)
                if src and catalog._empty(b.get(field)) and not catalog._empty(new.get(field)):
                    b[field] = new[field]
                    b.setdefault("field_sources", {})[field] = src
                    by_source[f"{field}:{src}"] = by_source.get(f"{field}:{src}", 0) + 1
                    changed = True
            after.append(b)
        if changed and not args.dry_run:
            f.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    cb, ca = coverage(before), coverage(after)
    n = len(before)
    print(f"routes: {len(files)}, stops: {n}, distinct books: {len(seen)}{' (dry run)' if args.dry_run else ''}")
    print(f"{'field':<10} {'before':>12} {'after':>12}")
    for field in FIELDS:
        print(f"{field:<10} {cb[field]:>4} ({100 * cb[field] // max(n, 1):>3}%) {ca[field]:>4} ({100 * ca[field] // max(n, 1):>3}%)")
    print("filled by source (stops):", ", ".join(f"{k}={v}" for k, v in sorted(by_source.items())) or "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
