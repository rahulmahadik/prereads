"""Build backend/data/libraries.json from the data.gov.sg "Libraries" GeoJSON (NLB).

    cd backend && .venv/bin/python scripts/fetch_libraries.py

    .venv/bin/python scripts/fetch_libraries.py --hours-only   # re-apply NLB hours, no download

Flow: poll-download -> signed URL -> GeoJSON -> name, address, lat/lng.
The dataset has no opening hours. Branches listed in data/nlb/branch_hours.json (built by
scripts/fetch_nlb_datasets.py from the nlb.gov.sg library pages) get those hours with
hours_source="NLB" and hours_as_of; the rest keep the typical default (10:00-21:00 daily)
with hours_source="default". DATAGOV_API_KEY is sent as x-api-key when set (never printed).
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # backend/ for app.*
from app.core import config  # noqa: E402
from app.integrations import nlb_datasets  # noqa: E402

DATASET_ID = "d_27b8dae65d9ca1539e14d09578b17cbf"
POLL = f"https://api-open.data.gov.sg/v1/public/api/datasets/{DATASET_ID}/poll-download"
OUT = Path(__file__).resolve().parent.parent / "data" / "libraries.json"
DEFAULT_HOURS = {"open": "10:00", "close": "21:00"}

# Branches the app uses that are missing from the dataset snapshot. Approximate public
# coordinates, flagged "manual" per record.
MANUAL_EXTRAS = [
    {"name": "Punggol Regional Library", "address": "1 Punggol Drive, Waterway Point, Singapore 828629", "lat": 1.4066, "lng": 103.9022},
]


def _get(url: str, tries: int = 6) -> httpx.Response:
    for i in range(tries):
        hdr = {"x-api-key": config.DATAGOV_API_KEY} if config.DATAGOV_API_KEY and "data.gov.sg" in url else {}
        r = httpx.get(url, timeout=60, follow_redirects=True, headers=hdr)
        body = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
        if r.status_code == 429 or body.get("name") == "TOO_MANY_REQUESTS":
            time.sleep(12 * (i + 1))
            continue
        return r
    raise RuntimeError(f"rate limited: {url}")


def _desc(props: dict) -> dict[str, str]:
    """Properties may be flat or carry an HTML <table> in 'Description'."""
    out = {k: str(v) for k, v in props.items() if k != "Description" and v is not None}
    html = props.get("Description") or ""
    for k, v in re.findall(r"<th>(.*?)</th>\s*<td>(.*?)</td>", html, flags=re.S):
        out[k.strip()] = re.sub(r"<[^>]+>", "", v).strip()
    return out


def _address(p: dict[str, str]) -> str:
    low = {k.lower(): v for k, v in p.items()}
    if low.get("address"):
        return low["address"]
    parts = [low.get("addressblockhousenumber"), low.get("addressstreetname"), low.get("addressbuildingname")]
    addr = " ".join(x for x in parts if x)
    if low.get("addresspostalcode"):
        addr += f", Singapore {low['addresspostalcode']}"
    return addr


def _name(p: dict[str, str]) -> str:
    low = {k.lower(): v for k, v in p.items()}
    return low.get("name") or low.get("library_name") or low.get("building_name") or ""


def apply_nlb_hours(lib: dict) -> dict:
    """Overlay the NLB page hours for this branch when data/nlb/branch_hours.json has them.
    A branch NLB lists as closed keeps its typical hours (hours_source "default") plus
    status "closed" and NLB's notice, so the UI can say so."""
    h = nlb_datasets.branch_hours(lib["name"])
    for k in ("status", "notice", "extended_open", "hours_as_of", "hours_url"):
        lib.pop(k, None)
    if not h:
        return lib
    lib["hours_as_of"], lib["hours_url"] = h.get("as_of"), h.get("url")
    if h.get("status") == "open" and h.get("open") and h.get("close"):
        lib["hours"] = {"open": h["open"], "close": h["close"]}
        lib["hours_source"] = "NLB"
        if h.get("extended_open"):
            lib["extended_open"] = h["extended_open"]
    elif h.get("status") == "closed":
        lib["status"], lib["notice"] = "closed", h.get("notice")
    return lib


def write(doc: dict) -> None:
    doc["libraries"] = [apply_nlb_hours(x) for x in doc["libraries"]]
    n = sum(1 for x in doc["libraries"] if x.get("hours_source") == "NLB")
    doc["hours_note"] = f"{n} branches use NLB's published hours; the rest are typical hours, check NLB."
    OUT.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {len(doc['libraries'])} libraries ({n} with NLB hours) to {OUT}")


def main() -> int:
    if "--hours-only" in sys.argv:
        write(json.loads(OUT.read_text()))
        return 0
    poll = _get(POLL).json()
    url = (poll.get("data") or {}).get("url")
    if not url:
        print("poll-download gave no url:", poll, file=sys.stderr)
        return 1
    geo = _get(url).json()
    libs = []
    for f in geo["features"]:
        geom = f.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lng, lat = geom["coordinates"][:2]
        p = _desc(f.get("properties") or {})
        name = _name(p)
        if not name:
            continue
        libs.append(
            {
                "name": name,
                "address": _address(p),
                "lat": round(lat, 6),
                "lng": round(lng, 6),
                "hours": DEFAULT_HOURS,
                "hours_source": "default",
            }
        )
    have = {x["name"].lower() for x in libs}
    for e in MANUAL_EXTRAS:
        if e["name"].lower() not in have:
            libs.append({**e, "hours": DEFAULT_HOURS, "hours_source": "default", "source": "manual"})
    libs.sort(key=lambda x: x["name"])
    OUT.parent.mkdir(parents=True, exist_ok=True)
    write({"source": "data.gov.sg", "dataset_id": DATASET_ID, "hours_note": "", "libraries": libs})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
