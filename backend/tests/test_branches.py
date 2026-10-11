from datetime import datetime

from fastapi.testclient import TestClient

from app.integrations.availability import BRANCHES
from app.main import app


def test_every_branch_has_sg_coordinates_and_parsable_hours():
    rows = TestClient(app).get("/api/branches").json()["branches"]
    assert {r["code"] for r in rows} == set(BRANCHES)
    for r in rows:
        assert r["name"] == BRANCHES[r["code"]]
        assert 1.15 <= r["lat"] <= 1.48, r["code"]
        assert 103.6 <= r["lng"] <= 104.1, r["code"]
        assert r["address"]
        o = datetime.strptime(r["hours"]["open"], "%H:%M")
        c = datetime.strptime(r["hours"]["close"], "%H:%M")
        assert o < c
