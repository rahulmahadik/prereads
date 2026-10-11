"""Precompute routes for every target in data/targets.json.

    python scripts/precompute.py                 # uses whatever keys are in .env
    DEMO=1 python scripts/precompute.py          # offline: seed picks + heuristics + demo availability
    python scripts/precompute.py --only "fast and slow" --refresh

Run this on Saturday with real keys so Sunday's demo is instant.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import catalog, config, llm  # noqa: E402
from app.engine import build_route, load_index, load_route, save_index, save_route, seeds  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="")
    ap.add_argument("--refresh", action="store_true", help="rebuild even if cached")
    ap.add_argument("--stale", action="store_true", help="rebuild only cached paths not yet model-judged (engine != llm)")
    args = ap.parse_args()

    llm.HEAVY = True
    print(f"mode: {config.mode()}  heavy model: {llm.resolve_model('heavy')}")
    index = {e["id"]: e for e in load_index()}
    done = failed = skipped = 0
    for i, seed in enumerate(seeds()):
        if args.limit and i >= args.limit:
            break
        if args.only and args.only.lower() not in seed["title"].lower():
            continue
        key = seed.get("isbn") or seed.get("id")
        cached = load_route(key) if key else None
        if cached and not args.refresh and not (args.stale and cached.engine != "llm"):
            skipped += 1
            continue
        t0 = time.time()
        try:
            route = build_route(seed)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {seed['title']}: {exc}")
            continue
        # Fill missing descriptions, covers, Dewey and years from open catalogues (cached).
        for st in route.stops:
            try:
                st.book = catalog.enrich(st.book)
            except Exception:  # noqa: BLE001 - enrichment is best effort
                pass
        # Seed ids stay stable: store under the seed key only, never under the catalogue's edition id.
        if key and key != route.target_id:
            route = route.model_copy(update={"target_id": key})
        save_route(route)
        target = next(s for s in route.stops if s.role == "target")
        index[route.target_id] = {"id": route.target_id, "title": target.book.title, "author": target.book.author, "cached": True}
        before = sum(1 for s in route.stops if s.role == "before")
        after = sum(1 for s in route.stops if s.role == "after")
        done += 1
        print(f"  ok   {target.book.title[:48]:48} before={before} after={after} engine={route.engine} {time.time()-t0:.1f}s")
    save_index(sorted(index.values(), key=lambda e: e["title"]))
    print(f"done={done} skipped={skipped} failed={failed} index={len(index)}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
