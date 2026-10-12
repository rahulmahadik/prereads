"""NLB open-data loaders and the shelf-data source switch (API > dataset > demo). No network."""
import json

import pytest
from fastapi.testclient import TestClient

from app.core import config
from app.core.models import Availability, Book
from app.integrations import availability, catalog, nlb_datasets as nd
from app.main import app

BISHAN = """Address 5 Bishan Place
Opening Hours
Mon - Sun: 10:00 AM - 09:00 PM


Extended hours: 09:00 AM – 10:00 AM
Staff-assisted services from 10:00 AM

Closed at 5.00pm on eves of Christmas, New Year, and Chinese New Year. Closed on Public Holidays.
Bookdrop : 24 hours"""
BUKIT_BATOK = "Opening Hours\nMon - Sun: 11:00 AM - 09:00 PM\n\nExtended hours: 09:00 AM – 11:00 AM\n"
AMK = ("Opening Hours\nAng Mo Kio Library will be closed from 1 Aug 2026 for relocation.\n"
       "Visit the self-service Browse-n-Borrow kiosk at level 4 of AMK Hub.\n\nBookdrop : Closed from 5:00pm on 21 Aug 2026")
CSV = """DataSeries,2000,2024,2023,1999
Public Libraries,na,29,28,na
Reach Index,na,69.9,78,na
Total Physical Collections,6065400,7932005,8034924,5419800
Loan Of Physical Library Materials,24543400,23988369,24423363,24757100
Usage Of Digital Library Materials,na,16459342,12711653,na
"""


@pytest.fixture
def nlb_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "NLB_DATA_DIR", tmp_path)
    nd._CACHE.clear()
    yield tmp_path
    nd._CACHE.clear()


def _write(d, name, data):
    (d / f"{name}.json").write_text(json.dumps(data))


@pytest.fixture
def no_keys(monkeypatch):
    monkeypatch.setattr(config, "NLB_API_KEY", "")
    monkeypatch.setattr(config, "NLB_APP_CODE", "")
    monkeypatch.setitem(config.RUNTIME, "demo", False)
    monkeypatch.setitem(config.RUNTIME, "use_nlb", None)
    monkeypatch.setitem(config.RUNTIME, "data_source", None)
    monkeypatch.setattr(config, "DATA_SOURCE", "auto")


@pytest.fixture
def keys(no_keys, monkeypatch):
    monkeypatch.setattr(config, "NLB_API_KEY", "k")
    monkeypatch.setattr(config, "NLB_APP_CODE", "c")


# ---------- parsers ----------

def test_parse_hours_daily_with_extended_hours():
    h = nd.parse_hours_text(BISHAN)
    assert h == {"status": "open", "open": "10:00", "close": "21:00", "extended_open": "09:00", "public_holidays": "closed"}
    assert nd.parse_hours_text(BUKIT_BATOK)["open"] == "11:00"


def test_parse_hours_closed_branch_keeps_the_notice():
    h = nd.parse_hours_text(AMK)
    assert h["status"] == "closed" and "open" not in h
    assert h["notice"] == "Ang Mo Kio Library will be closed from 1 Aug 2026 for relocation."


def test_parse_hours_unknown_page():
    assert nd.parse_hours_text("Something went wrong")["status"] == "unknown"


def test_reach_csv_parses_years_and_drops_na():
    s = nd.parse_reach_csv(CSV)
    assert s["Public Libraries"] == {2023: 28, 2024: 29}
    assert list(s["Loan Of Physical Library Materials"]) == [1999, 2000, 2023, 2024]
    st = nd.derive_stats(s)
    assert st["year"] == 2024
    assert st["values"]["physical_loans"] == 23988369 and st["values"]["reach_index"] == 69.9
    assert st["values"]["ebook_collection"] is None  # series not in this file


def test_branch_key_matches_all_naming_styles():
    assert nd.branch_key("Bishan Public Library") == nd.branch_key("Bishan Library") == nd.branch_key("bishan-library") == "bishan"
    assert nd.branch_key("Tampines Regional Library") == "tampines"


# ---------- loaders ----------

def test_loaders_are_empty_without_files(nlb_dir):
    assert nd.load("branch_hours") == {} and nd.as_of() is None
    assert nd.branch_hours("Bishan Public Library") is None and nd.headline() is None


def test_loaders_read_fixture_files(nlb_dir):
    _write(nlb_dir, "branch_hours", {"source": "NLB", "as_of": "2026-10-11", "branches": {"bishan": {"open": "10:00", "close": "21:00", "status": "open"}}})
    _write(nlb_dir, "library_stats", {"dataset": "Reach", "dataset_id": "d_x", "as_of": "2026-10-10", **nd.derive_stats(nd.parse_reach_csv(CSV))})
    assert nd.branch_hours("Bishan Library")["as_of"] == "2026-10-11"
    assert nd.as_of() == "2026-10-11"
    h = nd.headline()
    assert h["year"] == 2024 and h["physical_loans"] == 23988369 and h["dataset"] == "Reach"


def test_broken_file_is_empty_not_an_error(nlb_dir):
    (nlb_dir / "library_stats.json").write_text("{not json")
    assert nd.library_stats() == {}


# ---------- source resolution ----------

def test_auto_is_api_with_keys(keys, nlb_dir):
    assert config.effective_data_source() == "api"


def test_auto_is_dataset_without_keys_when_data_exists(no_keys, nlb_dir):
    _write(nlb_dir, "library_stats", {"as_of": "2026-10-11"})
    assert config.effective_data_source() == "dataset"


def test_auto_is_demo_with_nothing(no_keys, nlb_dir):
    assert config.effective_data_source() == "demo"


def test_forced_demo_wins_even_with_keys_and_data(keys, nlb_dir, monkeypatch):
    _write(nlb_dir, "library_stats", {"as_of": "2026-10-11"})
    monkeypatch.setattr(config, "DATA_SOURCE", "demo")
    assert config.effective_data_source() == "demo"


def test_forced_dataset_ignores_keys(keys, nlb_dir, monkeypatch):
    _write(nlb_dir, "library_stats", {"as_of": "2026-10-11"})
    monkeypatch.setitem(config.RUNTIME, "data_source", "dataset")
    assert config.effective_data_source() == "dataset"


def test_forced_dataset_without_data_falls_back_to_demo(no_keys, nlb_dir, monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "dataset")
    assert config.effective_data_source() == "demo"


def test_forced_api_without_key_falls_back(no_keys, nlb_dir, monkeypatch):
    monkeypatch.setitem(config.RUNTIME, "data_source", "api")
    assert config.effective_data_source() == "demo"
    _write(nlb_dir, "library_stats", {"as_of": "2026-10-11"})
    assert config.effective_data_source() == "dataset"


def test_runtime_override_beats_env(keys, nlb_dir, monkeypatch):
    monkeypatch.setattr(config, "DATA_SOURCE", "demo")
    monkeypatch.setitem(config.RUNTIME, "data_source", "api")
    assert config.effective_data_source() == "api"


def test_pick_priority_api_then_dataset_then_demo():
    assert nd.pick("A", "D", "X", src="api") == ("A", "api")
    assert nd.pick(None, "D", "X", src="api") == ("D", "nlb-dataset")
    assert nd.pick("A", "D", "X", src="dataset") == ("D", "nlb-dataset")
    assert nd.pick("A", None, "X", src="dataset") == ("X", "demo")
    assert nd.pick("A", "D", "X", src="demo") == ("X", "demo")


# ---------- availability respects the switch ----------

BOOK = Book(id="t1", title="Atomic Habits", author="James Clear")
LIVE = [Availability(branch="Bishan Public Library", branch_code="BIPL", call_number="158.1 CLE", available=1, total=2)]


def test_availability_api_mode_uses_live(keys, monkeypatch):
    monkeypatch.setattr(availability, "live_availability", lambda b: LIVE)
    assert availability.get_availability(BOOK) == LIVE


@pytest.mark.parametrize("forced", ["demo", "dataset"])
def test_availability_demo_and_dataset_modes_use_the_demo_table(keys, monkeypatch, forced):
    monkeypatch.setattr(availability, "live_availability", lambda b: pytest.fail("API called"))
    monkeypatch.setitem(config.RUNTIME, "data_source", forced)
    rows = availability.get_availability(BOOK)
    assert rows and all(r.demo for r in rows)
    assert availability.get_demand(BOOK, rows).demo


# ---------- endpoints ----------

def test_mode_endpoint_sets_and_reports_data_source(no_keys):
    c = TestClient(app)
    m = c.post("/api/mode", json={"data_source": "demo"}).json()
    assert m["data_source"] == "demo" and m["data_source_effective"] == "demo"
    m = c.post("/api/mode", json={"data_source": "api"}).json()
    assert m["data_source"] == "api" and m["data_source_effective"] in ("dataset", "demo")  # no key
    assert "dataset_as_of" in m
    assert c.post("/api/mode", json={"data_source": "bogus"}).status_code == 422


def test_branches_report_nlb_hours_unless_demo_is_forced(no_keys, monkeypatch):
    c = TestClient(app)
    monkeypatch.setitem(config.RUNTIME, "data_source", "dataset")
    r = c.get("/api/branches").json()
    bb = next(b for b in r["branches"] if b["code"] == "BBPL")
    if bb["hours_source"] == "NLB":  # the committed libraries.json carries NLB hours
        assert r["source"] == "nlb-dataset" and bb["hours_as_of"]
    monkeypatch.setitem(config.RUNTIME, "data_source", "demo")
    r = c.get("/api/branches").json()
    assert r["source"] == "demo" and r["as_of"] is None
    assert all(b["hours_source"] != "NLB" and "notice" not in b for b in r["branches"])


def test_popular_has_source_and_facts_fields(no_keys, nlb_dir, monkeypatch):
    _write(nlb_dir, "library_stats", {"dataset": "Reach", "dataset_id": "d_x", "as_of": "2026-10-11", **nd.derive_stats(nd.parse_reach_csv(CSV))})
    c = TestClient(app)
    r = c.get("/api/popular").json()
    assert r["source"] == "demo"  # no per-title open dataset; never invented
    assert all(x["source"] == "demo" and x["demo"] for x in r["popular"])
    assert r["facts"]["year"] == 2024 and r["facts"]["physical_loans"] == 23988369
    monkeypatch.setitem(config.RUNTIME, "data_source", "demo")
    assert c.get("/api/popular").json()["facts"] is None


def test_dataset_source_makes_no_catalogue_calls_even_with_keys(keys, monkeypatch):
    # the public site runs on open data while the Catalogue integration is finished
    monkeypatch.setattr(config, "DATA_SOURCE", "dataset")
    assert config.nlb_enabled() is False
    assert catalog.NLBClient()._get("GetTitles", Title="Sapiens") is None
    monkeypatch.setattr(config, "DATA_SOURCE", "api")
    assert config.nlb_enabled() is True
