"""Protection for a public site: request size limits, per-visitor rate limits and upload checks.

- BodyLimit: a request body over its limit gets 413 before the app reads it (Content-Length up front,
  and a running count for chunked bodies that don't declare one).
- RateLimit: requests per visitor IP per minute, overall and for the expensive endpoints. Limits are
  generous on purpose: offices and mobile networks put many readers behind one IP.
- image_kind(): only real JPEG / PNG / WebP / GIF / HEIC images with sane dimensions reach the vision model.

The visitor IP is Cloudflare's CF-Connecting-IP; requests from this machine without it (health checks,
tests, the operator) are never rate limited."""
from __future__ import annotations

import json
import struct
import threading
import time
from collections import defaultdict, deque
from typing import Optional

BODY_LIMITS = [("/api/scan", 8_000_000), ("/api/stt", 12_000_000)]
BODY_DEFAULT = 256_000                      # JSON bodies: a chat turn with its memory is ~20 KB

# (path prefix, requests per minute per visitor IP); the first match wins, then the overall limit applies too
RATE_RULES = [
    ("/api/scan", 10), ("/api/stt", 20), ("/api/tts", 60), ("/api/ask", 40),
    ("/api/chat", 120), ("/api/discover", 120), ("/api/resolve", 120),
    ("/api/route", 240), ("/api/digital", 240), ("/api/online", 240), ("/api/similar", 240),
]
RATE_ALL = 2000


def client_ip(scope) -> str:
    for k, v in scope.get("headers") or []:
        if k == b"cf-connecting-ip":
            return v.decode("latin-1").strip()
    client = scope.get("client")
    return client[0] if client else ""


def is_local(scope) -> bool:
    """This machine itself (no Cloudflare header, loopback client): health checks, tests, the operator."""
    if any(k == b"cf-connecting-ip" for k, _ in scope.get("headers") or []):
        return False
    client = scope.get("client")
    return bool(client) and client[0] in ("127.0.0.1", "::1", "localhost", "testclient")


async def _reply(send, status: int, detail: str, headers: Optional[list] = None) -> None:
    body = json.dumps({"detail": detail}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())] + (headers or [])})
    await send({"type": "http.response.body", "body": body})


class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        path = scope.get("path", "")
        limit = next((n for p, n in BODY_LIMITS if path.startswith(p)), BODY_DEFAULT)
        declared = next((v for k, v in scope.get("headers") or [] if k == b"content-length"), None)
        if declared is not None:
            try:
                if int(declared) > limit:
                    return await _reply(send, 413, f"Request too large (limit {limit // 1000} KB).")
            except ValueError:
                return await _reply(send, 400, "Bad Content-Length.")
        if declared is not None:                   # h11 holds the client to its declared length
            return await self.app(scope, receive, send)
        # No declared size (chunked): read it here, up to the limit, then hand the app a replay.
        chunks, seen = [], 0
        while True:
            msg = await receive()
            if msg["type"] != "http.request":
                return
            body = msg.get("body", b"")
            seen += len(body)
            if seen > limit:
                return await _reply(send, 413, f"Request too large (limit {limit // 1000} KB).")
            chunks.append(body)
            if not msg.get("more_body"):
                break
        replay = [{"type": "http.request", "body": b"".join(chunks), "more_body": False}]

        async def replayed():
            return replay.pop(0) if replay else await receive()

        await self.app(scope, replayed, send)


class RateLimit:
    def __init__(self, app, clock=time.monotonic):
        self.app = app
        self.clock = clock
        self.hits: dict[tuple[str, str], deque] = defaultdict(deque)
        self.lock = threading.Lock()
        self.last_sweep = 0.0
        self.reported: dict[str, float] = {}

    def _allow(self, ip: str, bucket: str, per_minute: int, now: float) -> bool:
        q = self.hits[(ip, bucket)]
        while q and now - q[0] >= 60:
            q.popleft()
        if len(q) >= per_minute:
            return False
        q.append(now)
        return True

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or is_local(scope):
            return await self.app(scope, receive, send)
        ip, path, now = client_ip(scope), scope.get("path", ""), self.clock()
        rule = next(((p, n) for p, n in RATE_RULES if path.startswith(p)), None)
        with self.lock:
            if now - self.last_sweep > 300:          # forget visitors idle for a minute or more
                for k in [k for k, q in self.hits.items() if not q or now - q[-1] >= 60]:
                    del self.hits[k]
                self.last_sweep = now
            ok = self._allow(ip, "*", RATE_ALL, now) and (rule is None or self._allow(ip, rule[0], rule[1], now))
        if not ok:
            self._report(ip, path, now)
            return await _reply(send, 429, "Too many requests from this network; please slow down a little.", [(b"retry-after", b"30")])
        return await self.app(scope, receive, send)

    def _report(self, ip: str, path: str, now: float) -> None:
        """One line per blocked visitor per minute in the visit log, so a flood shows up without
        the log itself growing with every refused request."""
        from . import config

        if not config.VISIT_LOG or now - self.reported.get(ip, -1e9) < 60:
            return
        self.reported[ip] = now
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "ip": ip, "country": "", "method": "", "path": path,
               "query": "", "status": 429, "ua": "rate limited"}
        try:
            with open(config.VISIT_LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec) + "\n")
        except OSError:
            pass


# ------------------------------------------------------------------ uploads
MAX_SIDE = 12_000
MAX_PIXELS = 50_000_000


def _png_size(b: bytes) -> Optional[tuple[int, int]]:
    if len(b) >= 24 and b[12:16] == b"IHDR":
        return struct.unpack(">II", b[16:24])
    return None


def _jpeg_size(b: bytes) -> Optional[tuple[int, int]]:
    i = 2
    while i + 9 < len(b):
        if b[i] != 0xFF:
            i += 1
            continue
        marker = b[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        seg = struct.unpack(">H", b[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF):
            h, w = struct.unpack(">HH", b[i + 5:i + 9])
            return w, h
        i += 2 + seg
    return None


def image_kind(data: bytes) -> Optional[str]:
    """The image's real media type from its bytes, or None for anything that is not a sane image
    (a script or HTML renamed .jpg, an empty file, a decompression bomb with absurd dimensions)."""
    if len(data) < 64:
        return None
    head = data[:32]
    if head.startswith(b"\xff\xd8\xff"):
        kind, size = "image/jpeg", _jpeg_size(data[:2_000_000])
    elif head.startswith(b"\x89PNG\r\n\x1a\n"):
        kind, size = "image/png", _png_size(data)
    elif head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        kind, size = "image/webp", None
    elif head[:6] in (b"GIF87a", b"GIF89a"):
        kind, size = "image/gif", struct.unpack("<HH", head[6:10])
    elif head[4:8] == b"ftyp" and head[8:12] in (b"heic", b"heix", b"mif1", b"msf1", b"hevc"):
        kind, size = "image/heic", None
    else:
        return None
    if size is not None:
        w, h = size
        if w <= 0 or h <= 0 or w > MAX_SIDE or h > MAX_SIDE or w * h > MAX_PIXELS:
            return None
    return kind
