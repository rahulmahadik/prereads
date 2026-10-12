"""Many readers at once: model calls take a slot; with every slot taken, chat and AI ranking answer
straight away without the model instead of queueing behind other readers."""
import time

from fastapi.testclient import TestClient

from app.ai import llm
from app.core import config
from app.main import app
from app.services import chat, discover


def test_slots_are_limited_and_given_back(monkeypatch):
    monkeypatch.setattr(config, "LLM_MAX_PENDING", 2)
    monkeypatch.setattr(llm, "_pending", 0)
    assert llm.reserve() and llm.reserve()
    assert llm.reserve() is False
    llm.release()
    assert llm.reserve() is True
    llm.release(); llm.release()
    assert llm.pending() == 0


def test_chat_answers_at_once_when_the_model_is_full(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "LLM_MAX_PENDING", 1)
    monkeypatch.setattr(llm, "_pending", 1)                 # another reader holds the only slot
    called = []
    monkeypatch.setattr(llm, "structured", lambda *a, **k: called.append(1) or time.sleep(5))
    t = time.perf_counter()
    r = TestClient(app).post("/api/chat", json={"text": "I want to understand investing", "state": {"step": "start"}}).json()
    assert time.perf_counter() - t < 2 and not called
    assert r["options"] and r["state"]["step"] == "pick"
    assert any("AI busy with other readers" in s["detail"] for s in r["trace"])


def test_chat_gives_its_slot_back(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(llm, "_pending", 0)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: None)
    TestClient(app).post("/api/chat", json={"text": "I want to understand investing", "state": {"step": "start"}})
    for _ in range(50):
        if llm.pending() == 0:
            break
        time.sleep(0.02)
    assert llm.pending() == 0


def test_ai_ranking_says_busy_at_once_but_still_serves_a_saved_answer(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    monkeypatch.setattr(config, "LLM_MAX_PENDING", 1)
    monkeypatch.setattr(llm, "_pending", 1)
    monkeypatch.setattr(llm, "structured", lambda *a, **k: time.sleep(5))
    monkeypatch.setattr(discover, "_rerank_disk_get", lambda key: None)
    c = TestClient(app)
    t = time.perf_counter()
    r = c.post("/api/discover", json={"text": "a gentle start on investing for a busy reader", "mode": "deep"}).json()
    assert time.perf_counter() - t < 3
    assert r["ai"] == "busy" and r["results"]
    # a saved answer for the same question is served even while the model is full
    first = r["results"][1]["id"]
    monkeypatch.setattr(discover, "rerank", lambda need, q, cands, lang=None, cache_only=False:
                        discover.Reranked(need=need, picks=[(first, "Saved pick")], cached=True))
    r2 = c.post("/api/discover", json={"text": "a gentle start on investing for a busy reader", "mode": "deep"}).json()
    assert r2["ai"] == "ok" and r2["results"][0]["id"] == first


def test_ttl_cache_shares_one_answer_then_refreshes(monkeypatch):
    from app.core import ttl

    clock = [100.0]
    monkeypatch.setattr(ttl.time, "monotonic", lambda: clock[0])
    calls = []

    @ttl.ttl_cache(60)
    def build(x):
        calls.append(x)
        return {"x": x, "n": len(calls)}

    assert build(1) == build(1) == {"x": 1, "n": 1}
    assert build(2)["n"] == 2                      # another key is its own entry
    clock[0] += 61
    assert build(1)["n"] == 3                      # expired: rebuilt


def test_voice_says_busy_with_429_so_the_page_uses_the_browser_voice(monkeypatch, tmp_path):
    from app.ai import tts

    monkeypatch.setattr(config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(config, "effective_demo", lambda: False)
    monkeypatch.setattr(tts, "TTS_DIR", tmp_path)
    monkeypatch.setattr(tts, "TTS_MAX_PENDING", 1)
    monkeypatch.setattr(tts, "_pending", 1)                        # another reader's voice is being made
    r = TestClient(app).post("/api/tts", json={"text": "A sentence nobody has heard yet."})
    assert r.status_code == 429
    # a voice already made is still served while busy
    key_text = "Already made."
    monkeypatch.setattr(tts, "_speak_kokoro", lambda text, voice=None: b"RIFFwav")
    monkeypatch.setattr(tts, "_pending", 0)
    assert TestClient(app).post("/api/tts", json={"text": key_text}).status_code == 200
    monkeypatch.setattr(tts, "_pending", 1)
    assert TestClient(app).post("/api/tts", json={"text": key_text}).status_code == 200
    assert tts._pending == 1                                        # served from disk, no slot taken


def test_page_routes_are_async_so_they_never_wait_for_worker_threads():
    import inspect

    from app.api import routes_chat
    from app import main

    spa = next(r.endpoint for r in main.app.routes if getattr(r, "path", "") == "/{path:path}")
    assert inspect.iscoroutinefunction(spa)
    assert inspect.iscoroutinefunction(routes_chat.chat_stream)


def test_ttl_cache_builds_once_for_a_crowd():
    import threading

    from app.core import ttl

    calls = []

    @ttl.ttl_cache(60)
    def slow():
        calls.append(1)
        time.sleep(0.2)
        return "list"

    out = []
    ts = [threading.Thread(target=lambda: out.append(slow())) for _ in range(20)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert out == ["list"] * 20 and len(calls) == 1
