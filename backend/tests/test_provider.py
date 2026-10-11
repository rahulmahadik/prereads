"""Provider layer: schema request, one retry on invalid JSON, model fallback. No network."""
from __future__ import annotations

from types import SimpleNamespace

from app.core import config
from app.ai import llm
from app.core.models import Judgment


class FakeCompletions:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=self.replies.pop(0)))])


def _fake(monkeypatch, replies):
    comp = FakeCompletions(replies)
    monkeypatch.setattr(llm, "client", lambda: SimpleNamespace(chat=SimpleNamespace(completions=comp)))
    monkeypatch.setattr(config, "AI_PROVIDER", "ollama")
    monkeypatch.setattr(llm, "installed_models", lambda max_age=15.0: ["gemma3:12b"])
    return comp


GOOD = '{"relation":"prepares_for","confidence":0.8,"reason":"Covers the biases first."}'


def test_structured_sends_json_schema_and_validates(monkeypatch):
    comp = _fake(monkeypatch, [GOOD])
    j = llm.structured(Judgment, "sys", "user", temperature=0.2)
    assert j and j.relation == "prepares_for"
    rf = comp.calls[0]["response_format"]
    assert rf["type"] == "json_schema" and rf["json_schema"]["name"] == "Judgment"
    assert comp.calls[0]["temperature"] == 0.2


def test_structured_retries_once_on_invalid_json(monkeypatch):
    comp = _fake(monkeypatch, ["not json", GOOD])
    assert llm.structured(Judgment, "s", "u") is not None
    assert len(comp.calls) == 2


def test_structured_gives_up_after_two_bad_replies(monkeypatch):
    comp = _fake(monkeypatch, ["nope", '{"relation":"bogus","confidence":2,"reason":"x"}'])
    assert llm.structured(Judgment, "s", "u") is None
    assert len(comp.calls) == 2


def test_missing_model_falls_back_to_installed(monkeypatch):
    monkeypatch.setattr(llm, "installed_models", lambda max_age=15.0: ["gemma3:12b", "nomic-embed-text:latest"])
    assert llm.resolve_model("llm") == "gemma3:12b"        # gpt-oss:20b not pulled
    assert llm.resolve_model("embed") == "nomic-embed-text"  # :latest tag matches


def test_image_goes_in_as_data_url(monkeypatch):
    comp = _fake(monkeypatch, ['{"title":"Noise","author":"Daniel Kahneman","isbn":null,"confidence":0.9}'])
    r = llm.scan(b"\x89PNG", "image/png")
    assert r and r.title == "Noise"
    part = comp.calls[0]["messages"][1]["content"][1]
    assert part["image_url"]["url"].startswith("data:image/png;base64,")
