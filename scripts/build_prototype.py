#!/usr/bin/env python3
"""Build the static, offline PreReads prototype for GitHub Pages: docs/index.html (one file).

    python3 scripts/build_prototype.py [--api http://localhost:8000] [--out docs/index.html]

Needs the backend running (for /api/similar, /api/popular, /api/branches, ...) and node
(for the Vite build). The page gets window.__PREREADS_DATA__; frontend/src/api.ts serves
the GET endpoints from it when present. Stdlib only.
"""
import argparse, base64, json, re, shutil, subprocess, sys, tempfile, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend" / "data"
FRONTEND = ROOT / "frontend"
DOCS = ROOT / "docs"
LIMIT = 16 * 1024 * 1024


def get(api, path, timeout=30):
    with urllib.request.urlopen(api + path, timeout=timeout) as r:
        return json.load(r)


_prev = None


def previous(out):
    """Data embedded by an earlier run, used when the backend is too slow to answer."""
    global _prev
    if _prev is None:
        try:
            m = re.search(r"window\.__PREREADS_DATA__=(.*?);</script>", Path(out).read_text(encoding="utf-8"), re.S)
            _prev = json.loads(m.group(1).replace("<\\/", "</")) if m else {}
        except Exception:
            _prev = {}
    return _prev


def short(name):
    return name.replace(" Public Library", "").replace(" Regional Library", "").replace(" Library", "")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--api", default="http://localhost:8000", help="running backend to read data from")
    ap.add_argument("--out", default=str(DOCS / "index.html"), help="output file (default: docs/index.html)")
    args = ap.parse_args()
    api = args.api.rstrip("/")

    # 1. Vite build into a scratch dir (never frontend/dist).
    dist = Path(tempfile.mkdtemp(prefix="prereads-proto-"))
    subprocess.run(["npx", "vite", "build", "--base", "./", "--outDir", str(dist), "--emptyOutDir"], cwd=FRONTEND, check=True)

    # 2. Embedded data.
    seeds = json.loads((BACKEND / "targets.json").read_text())
    category = {(s.get("isbn") or s.get("id")): (s.get("subjects") or ["Other"])[0] for s in seeds}
    routes = {}
    for p in sorted((BACKEND / "cache" / "routes").glob("*.json")):
        r = json.loads(p.read_text())
        routes[r["target_id"]] = r
    index = [e for e in json.loads((BACKEND / "cache" / "index.json").read_text()) if e["id"] in routes]
    def fetch(path, key, pick, timeout=10):
        try:
            return pick(get(api, path, timeout=timeout))
        except Exception as e:  # backend busy or down: reuse the last build's copy
            old = previous(args.out).get(key)
            if old is None:
                sys.exit(f"{path} failed ({e}) and there is no earlier build to reuse")
            print(f"warning: {path} failed, reusing previous copy")
            return old
    mode = {"provider": "none", "openai_key": False, "nlb_key": False, "env_demo": True, "ollama": None}
    mode.update(demo=True, use_llm=False, use_nlb=False, prototype=True, mode="prototype+embedded-data", cached_routes=len(routes))
    targets = [t for t in fetch("/api/targets", "targets", lambda d: d["targets"]) if t["id"] in routes]
    popular = [x for x in fetch("/api/popular?limit=12", "popular", lambda d: d["popular"]) if x["id"] in routes]
    branches = fetch("/api/branches", "branches", lambda d: d["branches"])
    browse = {}
    old_browse = previous(args.out).get("browse", {})
    for by in ("author", "category"):
        try:
            browse[by] = get(api, f"/api/browse?by={by}", timeout=10)["groups"]
        except Exception:
            browse[by] = old_browse.get(by) or sys.exit("browse failed and no earlier build to reuse")

    # Catalogue (mirrors discover._catalogue / status_for) and books.
    catalogue, books = {}, {}
    for tid, r in routes.items():
        before = [x for x in r["stops"] if x["role"] == "before"]
        for st in r["stops"]:
            b = st["book"]
            if b["id"] in catalogue and catalogue[b["id"]]["is_target"]:
                continue
            av = st["availability"]
            names = [short(a["branch"]) for a in av if a["available"] > 0]
            status = f"Available at {names[0]}" if names else "All out \u2014 join the waiting list"
            tgt = st["role"] == "target"
            catalogue[b["id"]] = {
                "id": b["id"], "line_id": tid, "is_target": tgt, "title": b["title"], "author": b["author"],
                "category": category.get(tid, "Other"), "subjects": b.get("subjects") or [],
                "level": st["readiness"]["level"], "hours": st["readiness"]["hours"],
                "why": (st["readiness"].get("one_line") or (st["why"] if not tgt else "") or b.get("summary", ""))[:400],
                "status": status, "available_at": names, "hot_at": [short(h) for h in st["demand"]["hot_branches"]],
                "before_count": len([x for x in before if x["readiness"]["level"] < st["readiness"]["level"]]) if tgt else 0,
            }
            books[b["id"]] = {"id": b["id"], "title": b["title"], "author": b["author"],
                              "subjects": b.get("subjects") or [], "category": category.get(tid, "Other")}

    # /api/similar for every stop book; skip slow ones (uncached LLM calls).
    def sim(bid):
        try:
            return bid, get(api, "/api/similar?id=" + urllib.parse.quote(bid), timeout=3)["books"]
        except Exception:
            return bid, None
    with ThreadPoolExecutor(4) as ex:
        similar = {k: v for k, v in ex.map(sim, list(catalogue)) if v}
    # Fallback for the rest: shared subjects/category (same idea as the backend's keyword fallback).
    lines = {tid: next(st["book"] for st in r["stops"] if st["role"] == "target") for tid, r in routes.items()}
    subj = {k: {x.lower() for x in (v["subjects"] or [])} | {v["category"].lower()} for k, v in catalogue.items()}
    fallback = 0
    for me_id, me in catalogue.items():
        if me_id in similar:
            continue
        scored = []
        for o_id, o in catalogue.items():
            if o["line_id"] == me["line_id"]:
                continue
            shared = sorted(subj[me_id] & subj[o_id])
            if shared:
                scored.append((len(shared), o_id, shared))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out = []
        for n, o_id, shared in scored[:3]:
            o = catalogue[o_id]
            ln = lines[o["line_id"]]
            out.append({"id": o_id, "title": o["title"], "author": o["author"], "reason": f"Also about {', '.join(shared[:2])}.",
                        "level": o["level"], "hours": o["hours"], "status": o["status"], "line_id": o["line_id"],
                        "line_title": ln["title"], "line_author": ln["author"], "is_target": o["is_target"], "similarity": float(n)})
        if out:
            similar[me_id] = out
            fallback += 1
    print(f"keyword-fallback similar: {fallback}")
    print(f"routes={len(routes)} books={len(catalogue)} similar={len(similar)} targets={len(targets)}")

    data = {"mode": mode, "targets": targets, "popular": popular, "branches": branches, "browse": browse,
            "index": index, "routes": routes, "similar": similar, "books": books, "catalogue": list(catalogue.values())}
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")

    # 3. Inline CSS + JS + data into one html.
    html = (dist / "index.html").read_text()
    def read_asset(ref):
        return (dist / ref.lstrip("./")).read_text()
    html = re.sub(r'<link[^>]+rel="stylesheet"[^>]+href="([^"]+)"[^>]*>', lambda m: "<style>" + read_asset(m.group(1)) + "</style>", html)
    icon = (dist / "icon.svg")
    icon_uri = "data:image/svg+xml;base64," + base64.b64encode(icon.read_bytes()).decode() if icon.exists() else ""
    html = re.sub(r'<link[^>]+rel="manifest"[^>]*>\s*', "", html)
    html = re.sub(r'<link[^>]+href="[^"]*icon[^"]*"[^>]*>', lambda m: re.sub(r'href="[^"]*"', f'href="{icon_uri}"', m.group(0)) if icon_uri else "", html)
    html = re.sub(r'<link[^>]+rel="modulepreload"[^>]*>\s*', "", html)
    scripts = []
    def grab(m):
        scripts.append(read_asset(m.group(1)))
        return ""
    html = re.sub(r'<script[^>]+type="module"[^>]+src="([^"]+)"[^>]*></script>', grab, html)
    if not scripts:
        sys.exit("no module script found in built index.html")
    head_data = f"<script>window.__PREREADS_DATA__={blob};</script>"
    js = "\n".join(scripts)
    # No service worker in the single-file prototype (a root /sw.js would 404 on a Pages subpath).
    js = re.sub(r'navigator\.serviceWorker\.register\((["\'`])/sw\.js\1\)', "Promise.resolve()", js).replace("</script", "<\\/script")
    html = html.replace("</head>", head_data + "</head>", 1)
    html = html.replace("</body>", f'<script type="module">{js}</script></body>', 1)
    shutil.rmtree(dist, ignore_errors=True)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    (out.parent / ".nojekyll").write_text("")
    size = out.stat().st_size
    print(f"wrote {out} ({size / 1e6:.2f} MB)")
    if size > LIMIT:
        sys.exit("over 16 MB")


if __name__ == "__main__":
    main()
