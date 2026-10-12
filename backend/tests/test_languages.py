"""Requests in other scripts (Marathi, Chinese, Tamil...) search the English catalogue in English, and a
book that isn't found says why: it may not be in Singapore's public library (NLB) collection."""
from fastapi.testclient import TestClient

from app.ai import llm
from app.core import config
from app.main import app
from app.services import chat, discover


def _demo(monkeypatch):
    monkeypatch.setattr(config, "DEMO", True)
    monkeypatch.setattr(config, "llm_enabled", lambda: False)


def test_other_scripts_are_detected_and_english_is_not():
    for t in ("मला गुंतवणुकीबद्दल पुस्तके हवी आहेत", "ययाति", "我想了解投资", "முதலீடு பற்றிய நூல்கள்"):
        assert llm.needs_english(t), t
    for t in ("Thinking, Fast and Slow", "café books", "Sapiens", "123"):
        assert not llm.needs_english(t), t


def test_marathi_chat_is_read_in_english_and_answers_with_books(monkeypatch):
    _demo(monkeypatch)
    monkeypatch.setattr(llm, "english_query", lambda text: "Books on investing")
    r = TestClient(app).post("/api/chat", json={"text": "मला गुंतवणुकीबद्दल पुस्तके हवी आहेत", "state": {"step": "start"}}).json()
    assert r["state"]["step"] == "pick" and r["options"]
    step = next(s for s in r["trace"] if s["step"] == "Reading your language")
    assert "Books on investing" in step["detail"]
    assert r["state"]["history"][0]["text"] == "मला गुंतवणुकीबद्दल पुस्तके हवी आहेत"     # memory keeps their words


def test_when_the_language_cant_be_read_the_chat_says_so(monkeypatch):
    _demo(monkeypatch)
    monkeypatch.setattr(llm, "english_query", lambda text: None)
    r = TestClient(app).post("/api/chat", json={"text": "ययाति", "state": {"step": "start"}}).json()
    assert "English" in r["messages"][0] and r["options"]


def test_not_found_says_it_may_not_be_in_nlb_in_every_language(monkeypatch):
    for lang in ("en", "zh", "ms", "ta"):
        token = chat._LANG.set(lang)
        try:
            msg = chat._say("not_found", q="Some Book")
        finally:
            chat._LANG.reset(token)
        assert "NLB" in msg and "Some Book" in msg, lang


def test_a_path_built_for_an_earlier_reader_is_found_by_its_title(monkeypatch):
    _demo(monkeypatch)
    target = discover._catalogue()[0]
    monkeypatch.setattr(chat, "load_index", lambda: [{"id": target["line_id"], "title": "Yayati", "author": "V.S. Khandekar"}])
    monkeypatch.setattr(chat, "rules", lambda text, cat: None)
    r = TestClient(app).post("/api/chat", json={"text": "Yayati", "state": {"step": "start"}}).json()
    assert r["state"]["step"] == "level" and r["state"]["book_id"] == target["line_id"]


def test_title_search_and_main_search_translate_first(monkeypatch):
    _demo(monkeypatch)
    seen = []
    monkeypatch.setattr(llm, "english_query", lambda text: seen.append(text) or "Sapiens")
    c = TestClient(app)
    r = c.get("/api/resolve", params={"q": "सेपियन्स"}).json()
    assert any("Sapiens" in x["title"] for x in r["results"])
    d = c.post("/api/discover", json={"text": "सेपियन्स", "mode": "fast"}).json()
    assert d["results"] and seen == ["सेपियन्स", "सेपियन्स"]
