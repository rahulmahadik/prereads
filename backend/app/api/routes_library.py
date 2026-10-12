"""Library endpoints: the branch list (with location and hours) and eBook/audiobook
copies from NLB's OverDrive catalogue."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Query

from ..core import config
from ..core.ttl import ttl_cache
from ..integrations.availability import BRANCHES

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/digital")
def digital_copies(title: str = Query(..., min_length=1, max_length=300), author: str = Query("", max_length=200)):
    from ..integrations.digital import lookup
    return lookup(title, author)


@router.get("/online")
def online_copies(title: str = Query(..., min_length=1, max_length=300), author: str = Query("", max_length=200)):
    """Legally free online copies (Project Gutenberg, Open Library); {} when none or on failure."""
    from ..integrations.online import lookup
    return lookup(title, author)


@router.get("/online/chapter")
def online_chapter(gutenberg_id: int = Query(..., gt=0)):
    """First chapter of a public-domain Project Gutenberg book, for the in-app reader."""
    from ..integrations.online import chapter
    data = chapter(gutenberg_id)
    if not data:
        raise HTTPException(404, "No readable first chapter found")
    return data


def _branch_key(name: str) -> str:
    # The branch table and data.gov.sg name branches differently ("X Public Library" vs "X Library"),
    # so drop the type word and spaces before matching.
    return re.sub(r"\b(public|regional)\b|\s+", "", name.lower())


def _libraries_by_key() -> dict:
    """data/libraries.json (built by scripts/fetch_libraries.py) keyed by normalised name; {} if missing."""
    path = config.DATA_DIR / "libraries.json"
    try:
        return {_branch_key(x["name"]): x for x in json.loads(path.read_text())["libraries"]}
    except (OSError, ValueError, KeyError):
        return {}


TYPICAL_HOURS = {"open": "10:00", "close": "21:00"}


@router.get("/branches")
def branches():
    """Every branch code with name, lat/lng, address and hours; location fields are None when unknown.

    Hours: NLB's published hours (hours_source "NLB", hours_as_of) when libraries.json has them,
    else the typical 10:00-21:00 ("default"). DATA_SOURCE=demo forces the typical hours.
    status "closed" + notice when NLB lists the branch as closed (e.g. relocation)."""
    from ..integrations import nlb_datasets

    return _branches(nlb_datasets.source())


@ttl_cache(300)      # one answer per data source, shared by every reader for 5 minutes
def _branches(src: str) -> dict:
    from ..integrations import nlb_datasets

    libs = _libraries_by_key()
    out = []
    for c, n in BRANCHES.items():
        lib = libs.get(_branch_key(n), {})
        real = src != "demo" and lib.get("hours_source") == "NLB"
        row = {
            "code": c, "name": n,
            "lat": lib.get("lat"), "lng": lib.get("lng"),
            "address": lib.get("address"),
            "hours": lib.get("hours") if real or src != "demo" else (TYPICAL_HOURS if lib else None),
            "hours_source": "NLB" if real else ("default" if lib else None),
            "hours_as_of": lib.get("hours_as_of") if real else None,
        }
        if src != "demo" and lib.get("status") == "closed":
            row["status"], row["notice"], row["hours_as_of"] = "closed", lib.get("notice"), lib.get("hours_as_of")
        out.append(row)
    any_real = any(r["hours_source"] == "NLB" for r in out)
    return {"branches": out, "source": "nlb-dataset" if any_real else "demo", "as_of": nlb_datasets.as_of() if any_real else None}
