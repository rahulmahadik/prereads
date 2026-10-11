"""Real NLB open data, derived into small JSON files under data/nlb/ by
scripts/fetch_nlb_datasets.py, and the shelf-data source switch (api > dataset > demo).

Files (each carries "source", "as_of" and the dataset id or page URL it came from):
  branch_hours.json   opening hours per branch from the NLB library pages (nlb.gov.sg)
  library_stats.json  annual aggregates from data.gov.sg "National Library Board Library Reach
                      Index, Collections And Loans, Annual" (SingStat M890961, Singapore Open Data Licence)
  datasets.json       the survey: every NLB dataset found on data.gov.sg

There is no open per-title or per-branch loans dataset, so these files never produce
per-title numbers: "Popular right now" stays demo unless the NLB API is on, and the
aggregates are shown as aggregates.

Layer: integrations. Never raises into a request: a missing or broken file is {}.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..core import config

log = logging.getLogger("prereads.nlb_datasets")

_CACHE: dict[str, tuple[float, dict]] = {}


def load(name: str) -> dict:
    """data/nlb/<name>.json, re-read when the file changes; {} when missing or invalid."""
    path = config.NLB_DATA_DIR / f"{name}.json"
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    hit = _CACHE.get(name)
    if hit and hit[0] == mtime:
        return hit[1]
    try:
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError("not an object")
    except (OSError, ValueError) as exc:
        log.warning("bad dataset file %s: %s", path.name, exc)
        data = {}
    _CACHE[name] = (mtime, data)
    return data


def as_of() -> Optional[str]:
    """Latest as_of date across the derived files, or None when there are none."""
    dates = [d.get("as_of") for d in (load("branch_hours"), load("library_stats")) if d.get("as_of")]
    return max(dates) if dates else None


def source() -> str:
    """"api" | "dataset" | "demo" for this request (see config.effective_data_source)."""
    return config.effective_data_source()


# ---------- branch hours ----------

def branch_key(name: str) -> str:
    """"Bishan Public Library", "Bishan Library", "bishan-library" -> "bishan"."""
    return re.sub(r"\b(public|regional|library)\b|[\s\-]+", "", name.lower())


def branch_hours(name: str) -> Optional[dict]:
    """{open, close, extended_open?, status, notice?, url, as_of} for a branch, or None."""
    data = load("branch_hours")
    row = (data.get("branches") or {}).get(branch_key(name))
    if not row:
        return None
    return {**row, "as_of": data.get("as_of"), "source": data.get("source", "NLB")}


def _clock(t: str) -> Optional[str]:
    """"10:00 AM" -> "10:00", "09:00 PM" -> "21:00"."""
    m = re.match(r"\s*(\d{1,2})(?:[:.](\d{2}))?\s*([AaPp])\.?[Mm]\.?", t)
    if not m:
        return None
    h, mins, ap = int(m.group(1)) % 12, m.group(2) or "00", m.group(3).lower()
    return f"{h + (12 if ap == 'p' else 0):02d}:{mins}"


def parse_hours_text(text: str) -> dict:
    """Parse the "Opening Hours" block of an NLB library page.

    Returns {status: "open"|"closed"|"unknown", open?, close?, extended_open?, notice?}.
    Daily hours look like "Mon - Sun: 10:00 AM - 09:00 PM"; a relocation or closure
    notice ("... will be closed from 1 Aug 2026 for relocation") gives status "closed"."""
    i = text.find("Opening Hours")
    block = text[i + len("Opening Hours"):] if i >= 0 else text
    block = block[:600]
    out: dict = {"status": "unknown"}
    closed = re.search(r"([^\n.]*\b(?:will be )?closed from [^\n.]*(?:\.|$))", block, flags=re.I)
    m = re.search(r"Mon\s*-\s*Sun\s*:\s*([0-9:.]+\s*[AP]M)\s*[-–]\s*([0-9:.]+\s*[AP]M)", block, flags=re.I)
    if m and _clock(m.group(1)) and _clock(m.group(2)):
        out.update(status="open", open=_clock(m.group(1)), close=_clock(m.group(2)))
        ext = re.search(r"Extended hours\s*:\s*([0-9:.]+\s*[AP]M)", block, flags=re.I)
        if ext and _clock(ext.group(1)):
            out["extended_open"] = _clock(ext.group(1))
    elif closed:
        out.update(status="closed", notice=closed.group(1).strip())
    if re.search(r"Closed on Public Holidays", block, flags=re.I):
        out["public_holidays"] = "closed"
    return out


# ---------- annual aggregates ----------

def library_stats() -> dict:
    """The derived aggregates: {source, dataset_id, dataset, as_of, year, values:{...}, series:{...}}."""
    return load("library_stats")


def headline() -> Optional[dict]:
    """One honest aggregate line for the Home row: the latest year's loans and digital use.
    None when the stats file is missing."""
    s = library_stats()
    vals = s.get("values") or {}
    if not s.get("year") or not vals.get("physical_loans"):
        return None
    return {
        "year": s["year"],
        "physical_loans": vals.get("physical_loans"),
        "digital_usage": vals.get("digital_usage"),
        "public_libraries": vals.get("public_libraries"),
        "reach_index": vals.get("reach_index"),
        "dataset": s.get("dataset"),
        "dataset_id": s.get("dataset_id"),
        "as_of": s.get("as_of"),
    }


def parse_reach_csv(text: str) -> dict:
    """SingStat-style CSV (DataSeries, then one column per year, "na" for gaps) ->
    {series_name: {year: number}}. Years sort numerically; "na" is dropped."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return {}
    head = [h.strip() for h in lines[0].split(",")]
    years = head[1:]
    out: dict[str, dict[int, float]] = {}
    for line in lines[1:]:
        cells = [c.strip() for c in line.split(",")]
        name, vals = cells[0], cells[1:]
        row: dict[int, float] = {}
        for y, v in zip(years, vals):
            if not y.isdigit() or v.lower() in {"na", "", "-"}:
                continue
            try:
                num = float(v)
            except ValueError:
                continue
            row[int(y)] = int(num) if num.is_integer() else num
        out[name] = dict(sorted(row.items()))
    return out


# Series name in the dataset -> our key.
SERIES = {
    "Public Libraries": "public_libraries",
    "Reach Index": "reach_index",
    "Total Physical Collections": "physical_collection",
    "Total Ebooks Collections": "ebook_collection",
    "Loan Of Physical Library Materials": "physical_loans",
    "Usage Of Digital Library Materials": "digital_usage",
}


def derive_stats(series: dict) -> dict:
    """Latest year that has physical loans, with every known series' value for that year."""
    loans = series.get("Loan Of Physical Library Materials") or {}
    if not loans:
        return {}
    year = max(loans)
    values = {key: series.get(name, {}).get(year) for name, key in SERIES.items()}
    history = {key: {str(y): v for y, v in series.get(name, {}).items() if y >= year - 9} for name, key in SERIES.items()}
    return {"year": year, "values": values, "series": history}


# ---------- source priority ----------

def pick(api_value, dataset_value, demo_value, src: Optional[str] = None):
    """API > dataset > demo, respecting the data-source switch: returns (value, "api"|"nlb-dataset"|"demo").
    A source that is off or gave nothing falls through to the next one."""
    src = src or source()
    if src == "api" and api_value:
        return api_value, "api"
    if src in ("api", "dataset") and dataset_value:
        return dataset_value, "nlb-dataset"
    return demo_value, "demo"
