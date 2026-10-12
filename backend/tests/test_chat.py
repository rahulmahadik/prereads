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
    shelves = next(s for s in r["trace"] if s["step"] == "Checking shelves")["detail"]
    assert "on a shelf now" in shelves and "demo" not in shelves
    assert not any("sample" in m or "demo" in m for m in r["messages"])
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
    assert "model test-model" in understood


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


# ------------------------------------------------------------------ conversation memory
def _say(c, text, state):
    return c.post("/api/chat", json={"text": text, "state": state}).json()


def _levels(state) -> list[int]:
    by_id = {e["id"]: e for e in discover._catalogue()}
    return [by_id[x["id"]]["level"] for x in state["candidates"]]


def test_follow_ups_refer_to_the_books_on_screen(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = _say(c, "investing", {"step": "start"})
    shown = r["state"]["candidates"]
    assert r["state"]["topic"] and len(r["state"]["history"]) == 2
    # "the second one" is the second book listed, not a title that happens to contain "Second"
    more = _say(c, "tell me more about the second one", r["state"])
    assert more["messages"][0].startswith(shown[1]["title"].split(":")[0].strip())
    assert any(s["step"] == "Using the conversation" for s in more["trace"])
    # "something easier": same subject, nothing already shown, easier than what was shown (or the gentlest left)
    easier = _say(c, "something easier", r["state"])
    ids = {x["id"] for x in easier["state"]["candidates"]}
    assert ids and ids <= _verified_ids() and not ids & {x["id"] for x in shown}
    assert "investing" in easier["messages"][0].lower()
    if "already the easiest" not in easier["messages"][0]:
        assert max(_levels(easier["state"])) < min(_levels(r["state"]))
    # "the first one" picks it, like tapping the option
    first = _say(c, "the first one", r["state"])
    assert first["state"]["step"] == "level" and first["state"]["focus_id"] == shown[0]["id"]


def test_side_question_mid_flow_keeps_the_pending_question(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = _say(c, "Fluent Python", {"step": "start"})
    assert r["state"]["step"] == "level"
    r = _say(c, "who wrote it?", r["state"])
    assert "Luciano Ramalho" in r["messages"][0]
    assert r["state"]["step"] == "level" and [o["value"] for o in r["options"]] == ["1", "3", "4"]
    r = _say(c, "I'm new to this", r["state"])
    assert r["state"]["step"] == "branch" and r["state"]["level"] == 1
    r = _say(c, "woodlands", r["state"])
    assert r["state"]["step"] == "done" and r["state"]["branch"] == "WRL"
    r = _say(c, "is it available at Tampines?", r["state"])
    assert "Tampines" in r["messages"][0] and "Fluent Python" in r["messages"][0]


def test_for_kids_keeps_the_subject_and_a_new_request_starts_fresh(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = _say(c, "investing", {"step": "start"})
    kids = _say(c, "what about for kids?", r["state"])
    assert "investing" in kids["messages"][0].lower()
    assert _levels(kids["state"]) == sorted(_levels(kids["state"]))
    new = _say(c, "books about sleep", r["state"])
    assert "Using the conversation" not in [s["step"] for s in new["trace"]]
    assert new["state"]["topic"] != r["state"]["topic"]


def test_ambiguous_it_answers_for_every_book_on_screen(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = _say(c, "investing", {"step": "start"})
    who = _say(c, "who wrote it?", r["state"])
    assert len(who["messages"]) == len(r["state"]["candidates"]) and all(" is by " in m for m in who["messages"])


def test_no_other_edition_of_a_book_already_shown():
    assert chat._edition_key("Python Crash Course, 2nd Edition") == chat._edition_key("Python crash course")
    assert chat._edition_key("Understanding Distributed Systems, Second Edition") == chat._edition_key("Understanding Distributed Systems")
    assert chat._edition_key("Sapiens: A Brief History of Humankind") == "sapiens"


def test_the_model_reads_a_follow_up_with_the_conversation(monkeypatch):
    _demo(monkeypatch, llm_on=True)
    seen = []

    def fake(schema, system, user, **kw):
        seen.append(json.loads(user))
        return None                     # fall back to scores; only the prompt matters here

    import json

    monkeypatch.setattr(llm, "structured", fake)
    monkeypatch.setattr(chat.embeddings, "available", lambda: False)
    c = TestClient(app)
    r = _say(c, "I want to understand investing", {"step": "start"})
    _say(c, "and the history of money", r["state"])
    assert "CONVERSATION" not in seen[0]
    convo = " ".join(seen[-1]["CONVERSATION"])
    assert "reader: I want to understand investing" in convo and "PreReads:" in convo
    assert "start over" not in convo


def test_start_over_clears_the_memory(monkeypatch):
    _demo(monkeypatch)
    c = TestClient(app)
    r = _say(c, "investing", {"step": "start"})
    r = _say(c, "start over", r["state"])
    assert r["state"]["history"] == [] and r["state"]["shown"] == [] and r["state"]["topic"] is None
