import pytest

from app.core import config


@pytest.fixture(autouse=True)
def _no_real_ai(monkeypatch):
    """Tests never reach a real model; individual tests opt in by patching llm_enabled."""
    monkeypatch.setattr(config, "AI_PROVIDER", "none")


@pytest.fixture(autouse=True)
def _no_real_visit_log(monkeypatch):
    """Test requests never land in the site's real visit log (VISIT_LOG from .env)."""
    monkeypatch.setattr(config, "VISIT_LOG", "")
