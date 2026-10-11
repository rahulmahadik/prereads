from fastapi.testclient import TestClient

from app.main import app
from app.services.suggest import suggestions


def test_suggestions_come_from_catalogue_and_language():
    en = suggestions("en", 4, seed=1)
    assert len(en["suggestions"]) == 4
    assert all(s["text"] and s["source"] for s in en["suggestions"])
    zh = suggestions("zh", 4, seed=1)
    assert zh["lang"] == "zh" and len(zh["suggestions"]) == 4
    assert suggestions("en", 4, seed=1) == en          # stable for a seed
    assert suggestions("xx", 2)["lang"] == "en"        # unknown language falls back


def test_suggestions_endpoint():
    r = TestClient(app).get("/api/suggestions?lang=ta&n=3&seed=2").json()
    assert r["lang"] == "ta" and len(r["suggestions"]) == 3
