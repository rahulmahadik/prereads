from fastapi.testclient import TestClient

from app import config
from app.main import app


def test_api_demo_mode(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    c = TestClient(app)
    assert c.get("/api/health").json()["ok"] is True
    hits = c.get("/api/resolve?q=black swan").json()["results"]
    assert hits and hits[0]["id"] == "9780812973815"
    r = c.get("/api/route?id=9780812973815")
    assert r.status_code == 200
    roles = [s["role"] for s in r.json()["stops"]]
    assert roles.index("target") > 0 and roles[-1] == "after"
    assert c.get("/api/route?id=nope").status_code == 404
    a = c.post("/api/ask", json={"target_id": "9780812973815", "intent": "time_budget", "weeks": 1}).json()
    assert "week" in a["answer"]
    assert c.post("/api/ask", json={"target_id": "nope", "intent": "why_before"}).status_code == 404
    s = c.post("/api/scan", files={"image": ("x.jpg", b"not-an-image", "image/jpeg")})
    assert s.status_code == 503
    assert len(c.get("/api/branches").json()["branches"]) >= 5
    assert len(c.get("/api/targets").json()["targets"]) >= 20


def test_browse_and_chat_demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    c = TestClient(app)
    groups = c.get("/api/browse?by=category").json()["groups"]
    assert groups and all({"label", "count", "ids"} <= set(g) for g in groups)
    books = c.get(f"/api/browse?ids={','.join(groups[0]['ids'])}").json()["books"]
    assert len(books) == groups[0]["count"]
    st = {"step": "start"}
    r = c.post("/api/chat", json={"text": "investing", "state": st}).json()
    assert r["state"]["step"] in ("level", "pick")
    if r["state"]["step"] == "pick":
        r = c.post("/api/chat", json={"text": "0", "state": r["state"]}).json()
    r = c.post("/api/chat", json={"text": "1", "state": r["state"]}).json()
    assert r["state"]["step"] == "branch"
    r = c.post("/api/chat", json={"text": "BIPL", "state": r["state"]}).json()
    assert r["result"] and r["result"]["start_id"]
    r = c.post("/api/chat", json={"text": "zzqx nothing", "state": {"step": "start"}}).json()
    assert "couldn't find" in r["messages"][0]


def test_discover_demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    c = TestClient(app)
    r = c.post("/api/discover", json={"text": "I want to understand investing but I only have 2 weeks", "branch": "BIPL"}).json()
    assert r["need"]["max_hours"] == 10
    assert any(ch["kind"] == "hours" for ch in r["chips"])
    assert r["results"] and all(0 < x["fit"] <= 1 for x in r["results"])
    on = [ch["id"] for ch in r["chips"] if ch["kind"] == "hours"]
    r2 = c.post("/api/discover", json={"text": "investing", "branch": "BIPL", "filters": on}).json()
    assert all(x["hours"] <= 10 for x in r2["results"])
    assert c.post("/api/discover", json={"text": "x"}).status_code == 422


def test_discover_and_resolve_paging(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: False)
    c = TestClient(app)
    q = {"text": "psychology economics history science", "branch": "", "offset": 0, "limit": 5}
    p1 = c.post("/api/discover", json=q).json()
    assert len(p1["results"]) == 5 and p1["total"] > 5 and p1["has_more"]
    p2 = c.post("/api/discover", json={**q, "offset": 5}).json()
    assert {r["id"] for r in p1["results"]}.isdisjoint({r["id"] for r in p2["results"]})
    r = c.get("/api/resolve?q=the&offset=0&limit=3").json()
    assert len(r["results"]) == 3 and r["total"] >= 3 and "has_more" in r


def test_stt_endpoint_transcribes_and_falls_back(monkeypatch):
    from fastapi.testclient import TestClient

    from app import stt
    from app.main import app

    c = TestClient(app)
    monkeypatch.setattr(stt, "available", lambda: True)
    monkeypatch.setattr(stt, "transcribe", lambda data, lang="en": "hello there")
    r = c.post("/api/stt", files={"audio": ("a.webm", b"123", "audio/webm")})
    assert r.status_code == 200 and r.json()["text"] == "hello there"
    monkeypatch.setattr(stt, "available", lambda: False)
    assert c.post("/api/stt", files={"audio": ("a.webm", b"123", "audio/webm")}).status_code == 503


def test_tts_local_caches_and_falls_back(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app import config, tts
    from app.main import app

    monkeypatch.setattr(config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    calls = []
    monkeypatch.setattr(tts, "_speak_kokoro", lambda text, voice: calls.append(text) or b"RIFFwav")
    c = TestClient(app)
    for _ in range(2):
        r = c.post("/api/tts", json={"text": "Hello reader"})
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.content == b"RIFFwav"
    assert calls == ["Hello reader"]  # second request served from the disk cache
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path / "empty")
    (tmp_path / "empty").mkdir()
    monkeypatch.setattr(tts, "_speak_kokoro", lambda text, voice: None)
    monkeypatch.setattr(tts, "_speak_say", lambda text: None)
    assert c.post("/api/tts", json={"text": "Nothing available"}).status_code == 503
