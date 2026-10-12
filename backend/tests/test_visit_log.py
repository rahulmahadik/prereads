import json

from fastapi.testclient import TestClient

from app.core import config
from app.main import app

PHONE = "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1"


def test_visit_log_is_off_unless_a_file_is_set(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "VISIT_LOG", "")
    TestClient(app).get("/api/branches")
    assert list(tmp_path.iterdir()) == []


def test_visit_log_records_the_visitor_behind_cloudflare(monkeypatch, tmp_path):
    f = tmp_path / "visits.jsonl"
    monkeypatch.setattr(config, "VISIT_LOG", str(f))
    c = TestClient(app)
    c.get("/api/branches?x=1", headers={"cf-connecting-ip": "203.0.113.7", "cf-ipcountry": "SG", "user-agent": PHONE})
    c.get("/api/health")                                    # health checks are not visits
    rows = [json.loads(line) for line in f.read_text().splitlines()]
    assert len(rows) == 1
    r = rows[0]
    assert (r["ip"], r["country"], r["path"], r["query"], r["status"]) == ("203.0.113.7", "SG", "/api/branches", "x=1", 200)
    assert "iPhone" in r["ua"] and r["t"]
