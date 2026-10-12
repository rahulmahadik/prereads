"""Public-site protection: no file outside the built frontend is ever served, oversized and flooding
requests are turned away, uploads must be real images, and expensive work can't be forced."""
import struct
import zlib

import pytest
from fastapi.testclient import TestClient

from app.ai import llm
from app.api import routes_paths
from app.core import config, guard
from app.main import app

CF = {"cf-connecting-ip": "203.0.113.9"}      # a visitor coming through Cloudflare


def _png(w: int, h: int) -> bytes:
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(b"\x00" * 64)) + chunk(b"IEND", b"")


def _jpeg(w: int, h: int) -> bytes:
    sof = b"\xff\xc0" + struct.pack(">HBHHB", 11, 8, h, w, 1) + b"\x01\x11\x00"
    return b"\xff\xd8\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00" + sof + b"\x00" * 64 + b"\xff\xd9"


@pytest.mark.skipif(not (config.REPO_ROOT / "frontend" / "dist" / "index.html").exists(), reason="needs a frontend build")
def test_encoded_dot_dot_never_reaches_files_outside_the_frontend():
    c = TestClient(app)
    for path in ("/..%2f..%2f.env", "/%2e%2e/%2e%2e/backend/app/main.py", "/..%2F..%2Fbackend%2Fapp%2Fcore%2Fconfig.py"):
        r = c.get(path)
        assert r.status_code in (200, 404), path
        assert "text/html" in r.headers.get("content-type", "") or r.status_code == 404, path
        assert "NLB_API_KEY" not in r.text and "from __future__" not in r.text, path


def test_a_body_over_the_limit_is_refused_even_without_a_declared_size():
    c = TestClient(app)
    big = b'{"text":"' + b"x" * 300_000 + b'","state":{}}'
    assert c.post("/api/chat", content=big, headers={"content-type": "application/json"}).status_code == 413

    def chunks():
        for _ in range(40):
            yield b"x" * 10_000
    r = c.post("/api/chat", content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_visitors_are_rate_limited_but_this_machine_is_not(monkeypatch):
    monkeypatch.setattr(guard, "RATE_RULES", [("/api/branches", 3)])
    c = TestClient(app)
    codes = [c.get("/api/branches", headers=CF).status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    assert c.get("/api/branches", headers={"cf-connecting-ip": "198.51.100.4"}).status_code == 200   # another visitor
    assert all(c.get("/api/branches").status_code == 200 for _ in range(6))                          # local


def test_only_real_images_with_sane_sizes_pass():
    assert guard.image_kind(_png(800, 1200)) == "image/png"
    assert guard.image_kind(_jpeg(1600, 2400)) == "image/jpeg"
    assert guard.image_kind(b"<script>alert(1)</script>" + b" " * 100) is None        # a script renamed .jpg
    assert guard.image_kind(b"#!/bin/sh\nrm -rf /\n" + b"#" * 100) is None
    assert guard.image_kind(_png(60_000, 60_000)) is None                               # decompression bomb
    assert guard.image_kind(_jpeg(20_000, 20_000)) is None
    assert guard.image_kind(b"") is None


def test_scan_refuses_non_images_and_waits_for_a_free_ai_slot(monkeypatch):
    monkeypatch.setattr(config, "llm_enabled", lambda: True)
    c = TestClient(app)
    r = c.post("/api/scan", files={"image": ("cover.jpg", b"<html><script>x</script></html>" + b" " * 200, "image/jpeg")})
    assert r.status_code == 415
    monkeypatch.setattr(config, "LLM_MAX_PENDING", 1)
    monkeypatch.setattr(llm, "_pending", 1)
    r = c.post("/api/scan", files={"image": ("cover.png", _png(600, 900), "image/png")})
    assert r.status_code == 429


def test_refresh_from_outside_is_ignored_and_builds_are_one_at_a_time(monkeypatch):
    built = []
    monkeypatch.setattr(config, "effective_demo", lambda: False)
    monkeypatch.setattr(routes_paths, "_build", lambda *a: built.append(a) or routes_paths.load_route("9780060555665"))
    c = TestClient(app)
    r = c.get("/api/route?id=9780060555665&refresh=true", headers=CF)
    assert r.status_code == 200 and built == []                 # served from cache, no rebuild
    assert routes_paths._build_lock.acquire(blocking=False)     # another build is running
    try:
        r = c.get("/api/route?id=9999999999999&title=Some+New+Book", headers=CF)
        assert r.status_code == 429 and built == []
    finally:
        routes_paths._build_lock.release()


def test_over_long_text_is_refused():
    c = TestClient(app)
    assert c.post("/api/chat", json={"text": "x" * 600, "state": {"step": "start"}}).status_code == 422
    assert c.post("/api/discover", json={"text": "x" * 600}).status_code == 422
    assert c.post("/api/tts", json={"text": "x" * 6000}).status_code == 422
    assert c.get("/api/resolve?q=" + "x" * 200).status_code == 422
