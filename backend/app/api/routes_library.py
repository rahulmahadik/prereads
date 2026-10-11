"""Library endpoints: the branch list (with location and hours) and eBook/audiobook
copies from NLB's OverDrive catalogue."""
from __future__ import annotations

import json
import re

from fastapi import APIRouter, HTTPException, Query

from ..core import config
from ..integrations.availability import BRANCHES

router = APIRouter(prefix="/api", tags=["library"])


@router.get("/digital")
def digital_copies(title: str = Query(..., min_length=1), author: str = ""):
    from ..integrations.digital import lookup
    return lookup(title, author)


@router.get("/online")
def online_copies(title: str = Query(..., min_length=1), author: str = ""):
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


@router.get("/branches")
def branches():
    """Every branch code with name, lat/lng, address and hours; location fields are None when unknown."""
    libs = _libraries_by_key()
    out = []
    for c, n in BRANCHES.items():
        lib = libs.get(_branch_key(n), {})
        out.append({
            "code": c, "name": n,
            "lat": lib.get("lat"), "lng": lib.get("lng"),
            "address": lib.get("address"), "hours": lib.get("hours"),
            "hours_source": lib.get("hours_source"),
        })
    return {"branches": out}
