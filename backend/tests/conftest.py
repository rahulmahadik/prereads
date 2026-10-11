import pytest

from app import config


@pytest.fixture(autouse=True)
def _no_real_ai(monkeypatch):
    """Tests never reach a real model; individual tests opt in by patching llm_enabled."""
    monkeypatch.setattr(config, "AI_PROVIDER", "none")
