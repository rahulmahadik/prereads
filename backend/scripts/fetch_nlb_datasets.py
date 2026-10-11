"""Rebuild backend/data/nlb/*.json from NLB open data.

    cd backend && .venv/bin/python scripts/fetch_nlb_datasets.py            # stats (+ hours if Playwright is installed)
    .venv/bin/python scripts/fetch_nlb_datasets.py --survey                  # also re-list every NLB dataset (465 pages)
    .venv/bin/python scripts/fetch_nlb_datasets.py --hours-from pages.json   # hours from pre-rendered page text

Outputs (small, committed, each with source + as_of):
  library_stats.json  data.gov.sg d_bf36da418f88e5485aff69079694ecef "National Library Board Library
                      Reach Index, Collections And Loans, Annual" (SingStat M890961). Singapore Open Data Licence.
  branch_hours.json   opening hours from each branch page on nlb.gov.sg (JS-rendered, so Playwright).
  datasets.json       every dataset managed by NLB (or naming a library) on data.gov.sg.

DATAGOV_API_KEY (.env) is sent as x-api-key when set; without it data.gov.sg rate-limits hard.
The key is never printed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ for app.*
from app.core import config  # noqa: E402
from app.integrations import nlb_datasets as nd  # noqa: E402

OUT = config.NLB_DATA_DIR
STATS_ID = "d_bf36da418f88e5485aff69079694ecef"
STATS_NAME = "National Library Board Library Reach Index, Collections And Loans, Annual"
SEARCH = "https://api-production.data.gov.sg/v2/public/api/datasets"
POLL = "https://api-open.data.gov.sg/v1/public/api/datasets/{id}/poll-download"
PAGE = "https://www.nlb.gov.sg/main/visit-us/our-libraries-and-locations/libraries/{slug}"
LICENCE = "Singapore Open Data Licence v1.0 (https://data.gov.sg/open-data-licence)"

# Our branch table (availability.BRANCHES) -> the slug of its page on nlb.gov.sg.
SLUGS = {
    "Bishan Public Library": "bishan-library",
    "Jurong West Public Library": "jurong-west-library",
    "Tampines Regional Library": "tampines-library",
    "Woodlands Regional Library": "woodlands-library",
    "Central Public Library": "central-library",
    "Punggol Regional Library": "punggol-library",
    "Bukit Batok Library": "bukit-batok-library",
    "Ang Mo Kio Public Library": "ang-mo-kio-library",
}


def headers() -> dict:
    return {"x-api-key": config.DATAGOV_API_KEY} if config.DATAGOV_API_KEY else {}


def get(url: str, tries: int = 6, **kw) -> httpx.Response:
    """GET with backoff on 429 / TOO_MANY_REQUESTS (data.gov.sg returns either)."""
    for i in range(tries):
        r = httpx.get(url, timeout=60, follow_redirects=True, headers=headers() if "data.gov.sg" in url else {}, **kw)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 429 or (isinstance(body, dict) and body.get("name") == "TOO_MANY_REQUESTS"):
            time.sleep(5 * (i + 1))
            continue
        return r
    raise RuntimeError(f"rate limited: {url}")


def download(dataset_id: str) -> bytes:
    """poll-download -> signed URL -> file bytes."""
    poll = get(POLL.format(id=dataset_id)).json()
    url = (poll.get("data") or {}).get("url")
    if not url:
        raise RuntimeError(f"poll-download gave no url for {dataset_id}: code={poll.get('code')}")
    return httpx.get(url, timeout=120, follow_redirects=True).content


def write(name: str, data: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote data/nlb/{name}.json")


def build_stats(today: str) -> None:
    series = nd.parse_reach_csv(download(STATS_ID).decode("utf-8-sig"))
    stats = nd.derive_stats(series)
    if not stats:
        raise RuntimeError("stats dataset had no loans series")
    write("library_stats", {
        "source": "data.gov.sg", "dataset_id": STATS_ID, "dataset": STATS_NAME,
        "origin": "National Library Board via SingStat table M890961", "licence": LICENCE,
        "as_of": today, "granularity": "annual, all of NLB (no per-branch or per-title split)", **stats,
    })


def build_hours(pages: dict[str, str], today: str) -> None:
    """pages: our branch name -> rendered page text."""
    rows = {}
    for name, text in pages.items():
        h = nd.parse_hours_text(text)
        if h["status"] == "unknown":
            print(f"  no hours parsed for {name}", file=sys.stderr)
            continue
        rows[nd.branch_key(name)] = {"name": name, "url": PAGE.format(slug=SLUGS.get(name, "")), **h}
    if rows:
        write("branch_hours", {"source": "NLB", "origin": "nlb.gov.sg library pages", "as_of": today, "branches": rows})


def render_pages() -> dict[str, str]:
    """Render each branch page with Playwright (optional; the pages are JS-rendered)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Playwright not installed: skipping hours (use --hours-from)", file=sys.stderr)
        return {}
    out = {}
    with sync_playwright() as p:
        b = p.chromium.launch(channel="chrome", headless=False)  # NLB's CDN blocks headless Chrome
        pg = b.new_page(locale="en-SG")
        for name, slug in SLUGS.items():
            try:
                pg.goto(PAGE.format(slug=slug), wait_until="networkidle", timeout=60000)
                out[name] = pg.inner_text("body")
            except Exception as exc:  # noqa: BLE001
                print(f"  {name}: {exc}", file=sys.stderr)
        b.close()
    return out


def survey(today: str, found: dict | None = None) -> None:
    """Every data.gov.sg dataset managed by NLB or naming a library. The search API ignores
    its query, so this pages through the whole catalogue."""
    if found is None:
        found, page, pages = {}, 1, 1
        while page <= pages:
            d = get(f"{SEARCH}?page={page}").json()["data"]
            pages = d.get("pages", pages)
            for x in d["datasets"]:
                if "library" in (x.get("managedByAgencyName") or "").lower() or "librar" in x["name"].lower():
                    found[x["datasetId"]] = x
            page += 1
    rows = sorted(
        ({"id": k, "name": x["name"], "agency": x.get("managedByAgencyName"), "format": x.get("format"),
          "coverage": [(x.get("coverageStart") or "")[:10] or None, (x.get("coverageEnd") or "")[:10] or None],
          "updated": (x.get("lastUpdatedAt") or "")[:10] or None} for k, x in found.items()),
        key=lambda r: r["name"],
    )
    write("datasets", {"source": "data.gov.sg", "as_of": today, "licence": LICENCE, "count": len(rows), "datasets": rows})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", action="store_true", help="re-list every NLB dataset (slow)")
    ap.add_argument("--survey-from", help="JSON {datasetId: dataset} from an earlier listing")
    ap.add_argument("--hours-from", help="JSON {branch name: rendered page text}")
    ap.add_argument("--no-stats", action="store_true")
    ap.add_argument("--no-hours", action="store_true")
    a = ap.parse_args()
    today = dt.date.today().isoformat()
    if not a.no_stats:
        build_stats(today)
    if not a.no_hours:
        pages = json.loads(Path(a.hours_from).read_text()) if a.hours_from else render_pages()
        if pages:
            build_hours(pages, today)
    if a.survey or a.survey_from:
        survey(today, json.loads(Path(a.survey_from).read_text()) if a.survey_from else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
