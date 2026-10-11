"""Re-score every cached reading line with the heavy local model and report problems.

    python scripts/eval_paths.py                      # rules + model
    python scripts/eval_paths.py --no-model           # rule checks only, no Ollama needed
    python scripts/eval_paths.py --limit 2 --only "fast" --json out.json

Read-only: the route cache is never modified. A model call that returns None is
counted as "model unavailable", never raised.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, llm  # noqa: E402
from app.engine import MAX_AFTER, MAX_BEFORE, MIN_CONFIDENCE  # noqa: E402
from app.models import Route  # noqa: E402


def _author_key(stop) -> str:
    # Same key engine._dedupe_author uses.
    return (stop.book.author or stop.book.title).lower().split(",")[0]


def check_rules(route: Route) -> list[str]:
    """Rule violations found in code, no model. Returns human-readable strings."""
    out: list[str] = []
    target = next((s for s in route.stops if s.role == "target"), None)
    if target is None:
        return ["no target stop in route"]
    before = [s for s in route.stops if s.role == "before"]
    after = [s for s in route.stops if s.role == "after"]
    t_level = target.readiness.level
    for s in before:
        if s.readiness.level >= t_level:
            out.append(f"before-book level {s.readiness.level} >= target level {t_level}: {s.book.title}")
        if s.confidence < MIN_CONFIDENCE:
            out.append(f"before-book confidence {s.confidence:.2f} < {MIN_CONFIDENCE}: {s.book.title}")
    if len(before) > MAX_BEFORE:
        out.append(f"{len(before)} before-books (max {MAX_BEFORE})")
    if len(after) > MAX_AFTER:
        out.append(f"{len(after)} after-books (max {MAX_AFTER})")
    seen: dict[str, str] = {}
    for s in before:
        k = _author_key(s)
        if k in seen:
            out.append(f"duplicate author on before-path ({k}): {seen[k]} / {s.book.title}")
        else:
            seen[k] = s.book.title
    for s in before + after:
        if s.book.id == target.book.id or s.book.id == route.target_id:
            out.append(f"target included in its own path: {s.book.title}")
    return out


def eval_model(route: Route) -> dict:
    """Re-judge each before->target hop and re-score readiness with the heavy model."""
    target = next(s for s in route.stops if s.role == "target")
    before = [s for s in route.stops if s.role == "before"]
    res = {"hops": [], "low_conf": 0, "not_easier": 0, "unavailable": 0, "judged": 0, "conf_sum": 0.0}

    rt = llm.readiness(target.book)
    if rt is None:
        res["unavailable"] += 1
    for s in before:
        rb = llm.readiness(s.book)
        if rb is None:
            res["unavailable"] += 1
        j = llm.judge(s.book, target.book, rb or s.readiness, rt or target.readiness)
        hop = {"before": s.book.title, "stored_level": s.readiness.level,
               "model_level": rb.level if rb else None, "target_model_level": rt.level if rt else None}
        if j is None:
            res["unavailable"] += 1
            hop["judgment"] = None
        else:
            res["judged"] += 1
            res["conf_sum"] += j.confidence
            hop["judgment"] = {"relation": j.relation, "confidence": j.confidence}
            if j.confidence < MIN_CONFIDENCE or j.relation != "prepares_for":
                res["low_conf"] += 1
                hop["flag"] = "low-confidence" if j.confidence < MIN_CONFIDENCE else f"relation {j.relation}"
        if rb is not None and rt is not None and rb.level >= rt.level:
            res["not_easier"] += 1
            hop["not_easier"] = "before-book not easier than target"
        res["hops"].append(hop)
    return res


def load_routes() -> list[tuple[str, Route]]:
    """Cached routes, deduped by target title, read-only."""
    seen: set[str] = set()
    out: list[tuple[str, Route]] = []
    for p in sorted(config.ROUTES_DIR.glob("*.json")):
        try:
            route = Route.model_validate_json(p.read_text(encoding="utf-8"))
            target = next(s for s in route.stops if s.role == "target")
        except Exception as exc:  # noqa: BLE001 - a half-written file must not stop the run
            print(f"  skip {p.name}: {exc}")
            continue
        key = target.book.title.strip().lower()
        if key in seen:
            continue
        seen.add(key)
        out.append((target.book.title, route))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", type=str, default="", help="title substring")
    ap.add_argument("--no-model", action="store_true", help="rule checks only")
    ap.add_argument("--json", type=str, default="", help="write full results here")
    args = ap.parse_args()

    use_model = not args.no_model
    llm.HEAVY = True
    model_name = llm.resolve_model("heavy") if use_model else "(none: --no-model)"
    if use_model and not config.llm_enabled():
        print("AI provider disabled; running rule checks only.")
        use_model = False
        model_name = "(none: AI_PROVIDER=none)"
    print(f"heavy model: {model_name}")

    t_all = time.time()
    routes = load_routes()
    if args.only:
        routes = [(t, r) for t, r in routes if args.only.lower() in t.lower()]
    if args.limit:
        routes = routes[: args.limit]

    results = []
    tot = {"hops": 0, "rules": 0, "low": 0, "ne": 0, "unavail": 0, "conf": 0.0}
    for title, route in routes:
        t0 = time.time()
        violations = check_rules(route)
        n_before = sum(1 for s in route.stops if s.role == "before")
        m = {"low_conf": 0, "not_easier": 0, "unavailable": 0, "judged": 0, "conf_sum": 0.0, "hops": []}
        if use_model:
            try:
                m = eval_model(route)
            except Exception as exc:  # noqa: BLE001 - never crash on a model failure
                m["unavailable"] += 1
                print(f"  model error on {title}: {exc}")
        secs = time.time() - t0
        tot["hops"] += m["judged"]
        tot["rules"] += len(violations)
        tot["low"] += m["low_conf"]
        tot["ne"] += m["not_easier"]
        tot["unavail"] += m["unavailable"]
        tot["conf"] += m["conf_sum"]
        extra = f" unavailable={m['unavailable']}" if m["unavailable"] else ""
        print(f"  {title[:44]:44} before={n_before} violations={len(violations)} low_conf={m['low_conf']} "
              f"not_easier={m['not_easier']}{extra} {secs:.1f}s")
        for v in violations:
            print(f"      rule: {v}")
        results.append({"title": title, "target_id": route.target_id, "n_before": n_before,
                        "violations": violations, "model": m, "seconds": round(secs, 1)})

    mean = f"{tot['conf'] / tot['hops']:.2f}" if tot["hops"] else "n/a"
    print("\n=== summary ===")
    print(f"titles evaluated:     {len(results)}")
    print(f"hops judged:          {tot['hops']}")
    print(f"rule violations:      {tot['rules']}")
    print(f"low-confidence hops:  {tot['low']}")
    print(f"not-easier hops:      {tot['ne']}")
    print(f"model unavailable:    {tot['unavail']}")
    print(f"mean hop confidence:  {mean}")
    print(f"model:                {model_name}")
    print(f"total time:           {time.time() - t_all:.1f}s")

    if args.json:
        Path(args.json).write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
