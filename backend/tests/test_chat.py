from fastapi.testclient import TestClient

from app.services import chat, discover
from app.core import config
from app.ai import llm
from app.main import app


def _demo(monkeypatch, llm_on=False):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: llm_on)


def _verified_ids() -> set[str]:
    return {e["id"] for e in discover._catalogue()}


def test_vague_input_gets_a_clarifying_turn(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    for text in ("books", "something good", "hi", "help me"):
        r = c.post("/api/chat", json={"text": text, "state": {"step": "start"}}).json()
        joined = " ".join(r["messages"]).lower()
        assert "couldn't find" not in joined, text
        assert 3 <= len(r["options"]) <= 4, text
        assert r["state"]["step"] == "start"
        assert r["trace"] and all({"step", "detail", "ms"} <= set(s) for s in r["trace"])
    # the options come from our data: subjects with real counts, and a catalogue-verified title
    values = [o["value"] for o in r["options"]]
    assert any(v.startswith("topic:") for v in values)
    books = [v[5:] for v in values if v.startswith("book:")]
    assert books and set(books) <= _verified_ids()


def test_topic_returns_verified_options_and_a_trace(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = c.post("/api/chat", json={"text": "investing", "state": {"step": "start"}}).json()
    assert r["state"]["step"] == "pick" and 1 <= len(r["options"]) <= 3
    ids = {x["id"] for x in r["state"]["candidates"]}
    assert ids and ids <= _verified_ids()
    steps = [s["step"] for s in r["trace"]]
    assert "Searching the catalogue" in steps and "Checking shelves" in steps
    search = next(s for s in r["trace"] if s["step"] == "Searching the catalogue")
    assert f"from {len(_verified_ids())} books" in search["detail"]
    assert "demo data" in next(s for s in r["trace"] if s["step"] == "Checking shelves")["detail"]
    # tapping an option continues to the level step, then branch, then a result with a trace
    r = c.post("/api/chat", json={"text": "0", "state": r["state"]}).json()
    assert r["state"]["step"] == "level"
    r = c.post("/api/chat", json={"text": "1", "state": r["state"]}).json()
    r = c.post("/api/chat", json={"text": "BIPL", "state": r["state"]}).json()
    assert r["result"]["start_id"] and [s["step"] for s in r["trace"]] == ["Building your reading path", "Checking shelves"]


def test_tapped_subject_and_popular_title(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = c.post("/api/chat", json={"text": "", "state": {"step": "start"}}).json()
    topic = next(o for o in r["options"] if o["value"].startswith("topic:"))
    book = next(o for o in r["options"] if o["value"].startswith("book:"))
    t = c.post("/api/chat", json={"text": topic["value"], "state": r["state"]}).json()
    assert t["state"]["step"] == "pick" and t["options"]
    b = c.post("/api/chat", json={"text": book["value"], "state": r["state"]}).json()
    assert b["state"]["step"] == "level" and b["state"]["book_id"]


def test_model_pick_outside_retrieved_list_is_dropped(monkeypatch):
    _demo(monkeypatch, llm_on=True)
    hits, _ = chat.retrieve("investing", discover._catalogue())
    real = hits[1][0]["id"]
    calls = []

    def fake(schema, system, user, **kw):
        calls.append(schema.__name__)
        if schema is chat.Understood:
            return chat.Understood(kind="topic", value="investing",
                                   picks=[chat.Pick(id="9999999999999", reason="Invented."), chat.Pick(id=real, reason="Plain and practical")])
        return None

    monkeypatch.setattr(llm, "structured", fake)
    monkeypatch.setattr(llm, "resolve_model", lambda kind="llm": "test-model")
    monkeypatch.setattr(config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(chat.embeddings, "available", lambda: False)
    r = TestClient(app).post("/api/chat", json={"text": "I want to understand investing", "state": {"step": "start"}}).json()
    assert calls == ["Understood"]   # one model call: understand + choose
    ids = [x["id"] for x in r["state"]["candidates"]]
    assert ids == [real] and "9999999999999" not in ids
    assert r["options"][0]["hint"].startswith("Plain and practical.")
    detail = next(s for s in r["trace"] if s["step"] == "Choosing the best 3")["detail"]
    assert "test-model picked 1 of" in detail and "1 unknown id dropped" in detail
    understood = next(s for s in r["trace"] if s["step"] == "Understanding your request")["detail"]
    assert "local model test-model" in understood


def test_named_book_and_nearest_when_missing(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = c.post("/api/chat", json={"text": "sapiens", "state": {"step": "start"}}).json()
    assert r["state"]["step"] == "level" and "Sapiens" in r["messages"][0]
    r = c.post("/api/chat", json={"text": "kahneman", "state": {"step": "start"}}).json()
    assert r["state"]["step"] == "pick" and all("Kahneman" in o["label"] for o in r["options"])


def test_slow_model_falls_back_within_budget(monkeypatch):
    import time as _t

    _demo(monkeypatch, llm_on=True)
    monkeypatch.setattr(chat, "MODEL_BUDGET", 0.05)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: _t.sleep(0.3))
    r = TestClient(app).post("/api/chat", json={"text": "I want to understand investing", "state": {"step": "start"}}).json()
    assert r["options"] and {x["id"] for x in r["state"]["candidates"]} <= _verified_ids()
    assert any("gave no answer" in s["detail"] for s in r["trace"])


def test_chat_stream_sends_real_steps_then_reply():
    import json

    from fastapi.testclient import TestClient

    from app.main import app

    c = TestClient(app)
    with c.stream("POST", "/api/chat/stream", json={"text": "investing", "state": {}}) as r:
        events = [json.loads(line) for line in r.iter_lines() if line]
    kinds = [e["type"] for e in events]
    assert kinds[-1] == "reply" and "start" in kinds and "done" in kinds
    starts = [e["step"] for e in events if e["type"] == "start"]
    dones = [e["step"] for e in events if e["type"] == "done"]
    assert starts == dones                      # every step that started also finished
    assert [s["step"] for s in events[-1]["reply"]["trace"]] == dones   # the stream matches the final trace
