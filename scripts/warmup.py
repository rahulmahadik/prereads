#!/usr/bin/env python3
"""Warm a running PreReads app: load the Ollama models and fill the disk caches.

    python3 scripts/warmup.py [--base http://localhost:8000] [--quick] [--examples FILE]

--quick skips similar/digital/online for paths outside the five showcase titles.
--examples sends extra prompts from a Markdown file: first-column table cells under
"## 1." go to discovery, those under "## 6." go to chat.
Stdlib only; safe to re-run (a second run is fast because everything is cached).
"""
import argparse
import json
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

TIMEOUT = 90
SHOWCASE_TITLES = [
    "The Intelligent Investor",
    "Thinking, Fast and Slow",
    "Fluent Python",
    "Deep Learning with Python",
    "Meditations",
]
CHAT_EXTRA = ["books", "kahneman"]

LOCK = threading.Lock()
STATS = []  # (label, seconds, ok, detail)


def call(base, method, path, body=None, params=None, label=None, raw=False):
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    t0 = time.time()
    ok, detail, out = True, "", None
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            payload = r.read()
        out = payload if raw else json.loads(payload or b"null")
    except urllib.error.HTTPError as e:
        ok, detail = False, f"HTTP {e.code}"
    except Exception as e:  # timeout, refused, bad json
        ok, detail = False, f"{type(e).__name__}: {e}"
    dt = time.time() - t0
    with LOCK:
        STATS.append((label or f"{method} {path}", dt, ok, detail))
    return out, dt, ok, detail


def say(msg):
    with LOCK:
        print(msg, flush=True)


def parse_examples(path):
    """Discovery prompts (section 1) and chat prompts (section 6) from a Markdown file."""
    discover, chat = [], list(CHAT_EXTRA)
    if not path or not path.exists():
        return discover, chat
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section = line
            continue
        m = re.match(r"^\|\s*(.+?)\s*\|", line)
        if not m:
            continue
        cell = m.group(1)
        if cell.lower() in ("type this", "say") or set(cell) <= set("-: "):
            continue
        if section.startswith("## 1."):
            discover.append(cell)
        elif section.startswith("## 6.") and not cell.lower().startswith("tap"):
            chat.append(cell)
    seen = set()
    chat = [c for c in chat if not (c in seen or seen.add(c))]
    return discover, chat


def stage_models(base):
    print("\n== 2. Loading models ==")
    jobs = [
        ("chat (llm)", "POST", "/api/chat", {"text": "I want to understand investing", "state": {}}, False),
        ("discover deep (llm)", "POST", "/api/discover",
         {"text": "AI for a beginner who knows some Python", "mode": "deep"}, False),
        ("discover fast (embeddings)", "POST", "/api/discover",
         {"text": "AI for a beginner who knows some Python", "mode": "fast"}, False),
        ("tts (kokoro)", "POST", "/api/tts", {"text": "Welcome to PreReads."}, True),
    ]
    for label, method, path, body, raw in jobs:
        _, dt, ok, detail = call(base, method, path, body, label=label, raw=raw)
        print(f"  {'ok  ' if ok else 'FAIL'} {label:<28} {dt:6.1f}s {detail}")


def warm_route(base, target):
    route, rdt, rok, rdetail = call(base, "GET", "/api/route", params={"id": target["id"]},
                                    label=f"route {target['title']}")
    say(f"  {'ok  ' if rok else 'FAIL'} {target['title']:<42} route {rdt:5.1f}s {rdetail}"
        + (f"  {len(route.get('stops') or [])} stops" if rok and isinstance(route, dict) else ""))
    return route if rok and isinstance(route, dict) else None


def warm_book(base, b):
    """similar + digital + online for one book (deduplicated across paths)."""
    q = {"title": b.get("title", ""), "author": b.get("author", "")}
    t0, times, fails = time.time(), [], 0
    for ep, params in (("/api/similar", {"id": b.get("id", "")}),
                       ("/api/digital", q), ("/api/online", q)):
        _, dt, ok, _d = call(base, "GET", ep, params=params,
                             label=f"{ep.split('/')[-1]} {b.get('title', '?')}")
        times.append(f"{ep.split('/')[-1]} {dt:.1f}s")
        fails += (not ok)
    say(f"  {'ok  ' if not fails else 'WARN'} {b.get('title', '?')[:42]:<42} "
        f"{', '.join(times)}  total {time.time()-t0:5.1f}s")


def stage_examples(base, discover, chat):
    print(f"\n== 4. Example prompts ({len(discover)} discovery, {len(chat)} chat) ==")
    jobs = []
    for t in discover:
        jobs.append((f"discover fast: {t[:40]}", "/api/discover", {"text": t, "mode": "fast"}))
        jobs.append((f"discover deep: {t[:40]}", "/api/discover", {"text": t, "mode": "deep"}))
    for t in chat:
        jobs.append((f"chat: {t[:40]}", "/api/chat", {"text": t, "state": {}}))

    def run(j):
        label, path, body = j
        _, dt, ok, detail = call(base, "POST", path, body, label=label)
        say(f"  {'ok  ' if ok else 'FAIL'} {label:<58} {dt:6.1f}s {detail}")

    with ThreadPoolExecutor(max_workers=2) as ex:  # LLM calls: keep modest
        list(ex.map(run, jobs))


def stage_tts(base, routes_by_title):
    print("\n== 5. Listen narration (TTS) for the showcase paths ==")
    for title in SHOWCASE_TITLES:
        route = routes_by_title.get(title)
        if not route:
            print(f"  skip {title} (no route)")
            continue
        before = [s["book"]["title"] for s in route.get("stops", []) if s.get("role") == "before"]
        text = f"{len(before)} books before {title}. " + ". ".join(before) + "."
        _, dt, ok, detail = call(base, "POST", "/api/tts", {"text": text},
                                 label=f"tts {title}", raw=True)
        print(f"  {'ok  ' if ok else 'FAIL'} {title:<42} {dt:6.1f}s {detail}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--quick", action="store_true",
                    help="skip similar/digital/online for non-showcase paths")
    ap.add_argument("--examples", type=Path, default=None,
                    help="Markdown file with extra discovery and chat prompts")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    T0 = time.time()

    print("== 1. Health and mode ==")
    h, _, ok1, d1 = call(base, "GET", "/api/health", label="health")
    m, _, ok2, d2 = call(base, "GET", "/api/mode", label="mode")
    if not (ok1 and ok2):
        print(f"cannot reach {base}: {d1 or d2}")
        return 2
    print(f"  health: {h}")
    models = ((m or {}).get("ollama") or {}).get("models") or {}
    print(f"  provider: {m.get('provider')}  demo: {m.get('demo')}  use_llm: {m.get('use_llm')}")
    for k, v in models.items():
        print(f"  {k:<6} {v.get('name')}  installed={v.get('installed')}")

    stage_models(base)

    print("\n== 3. Reading paths ==")
    tg, _, ok, d = call(base, "GET", "/api/targets", label="targets")
    targets = (tg or {}).get("targets", []) if ok else []
    print(f"  {len(targets)} cached targets{'  (quick)' if a.quick else ''}")
    with ThreadPoolExecutor(max_workers=4) as ex:
        results = list(ex.map(lambda t: warm_route(base, t), targets))
    routes = {t["title"]: r for t, r in zip(targets, results) if r}

    books = {}
    for t, r in zip(targets, results):
        if not r or (a.quick and t["title"] not in SHOWCASE_TITLES):
            continue
        for s_ in r.get("stops") or []:
            b = s_.get("book") or {}
            if b.get("id"):
                books.setdefault(b["id"], b)
    print(f"\n== 3b. similar / digital / online for {len(books)} unique books ==")
    with ThreadPoolExecutor(max_workers=4) as ex:
        list(ex.map(lambda b: warm_book(base, b), books.values()))

    discover, chat = parse_examples(a.examples)
    stage_examples(base, discover, chat)
    stage_tts(base, routes)

    total = time.time() - T0
    fails = [s for s in STATS if not s[2]]
    slowest = sorted(STATS, key=lambda s: -s[1])[:5]
    print("\n== Summary ==")
    print(f"  requests: {len(STATS)}   failures: {len(fails)}   total time: {total:.1f}s")
    print("  slowest 5:")
    for label, dt, ok, detail in slowest:
        print(f"    {dt:6.1f}s  {label[:70]}{'' if ok else '  FAILED ' + detail}")
    if fails:
        print("  failed:")
        for label, dt, _ok, detail in fails:
            print(f"    {label[:70]}  {detail}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
