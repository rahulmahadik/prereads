"""NLB's limits for our key are 1 request a second and 15 a minute. Every Catalogue call goes through
one limiter and a response cache; a call that would wait too long is skipped so the caller falls back."""
import httpx
import pytest

from app.core import config
from app.integrations import catalog
from app.integrations.catalog import NLBClient, RateLimiter


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.now += s


def test_limiter_spaces_calls_one_second_apart():
    clock = FakeClock()
    lim = RateLimiter(1, 15, clock=clock, sleep=clock.sleep)
    start = clock.now
    assert all(lim.acquire(max_wait=2) for _ in range(5))
    assert clock.now - start == pytest.approx(4.0)        # 5 calls: at 0, 1, 2, 3, 4 s


def test_margin_leaves_room_for_network_jitter():
    clock = FakeClock()
    lim = RateLimiter(1, 15, margin=0.5, clock=clock, sleep=clock.sleep)
    start = clock.now
    assert all(lim.acquire(max_wait=2) for _ in range(3))
    assert clock.now - start == pytest.approx(3.0)        # 1.5 s apart, not 1.0 (NLB answered 429 at 1.0)


def test_limiter_allows_15_a_minute_then_skips_rather_than_waiting():
    clock = FakeClock()
    lim = RateLimiter(1, 15, clock=clock, sleep=clock.sleep)
    start = clock.now
    assert all(lim.acquire(max_wait=2) for _ in range(15))
    assert lim.acquire(max_wait=2) is False                # the 16th would wait ~46 s
    clock.now = start + 60                                 # a minute after the first call
    assert lim.acquire(max_wait=2) is True


@pytest.fixture
def client(monkeypatch, tmp_path):
    calls: list[tuple[str, dict]] = []
    replies: list[httpx.Response] = []

    def fake_send(self, path, params):
        calls.append((path, dict(params or {})))
        return replies.pop(0) if replies else httpx.Response(200, json={"titles": [{"title": "Sapiens"}]})

    monkeypatch.setattr(config, "NLB_CACHE_DIR", tmp_path)
    monkeypatch.setattr(config, "NLB_MAX_WAIT", 2.0)
    monkeypatch.setattr(NLBClient, "_send", fake_send)
    monkeypatch.setattr(NLBClient, "enabled", lambda self: True)
    c = NLBClient()
    clock = FakeClock()
    c.limiter = RateLimiter(1, 15, clock=clock, sleep=clock.sleep)
    return c, calls, replies


def test_same_request_is_answered_from_the_cache(client):
    c, calls, _ = client
    assert c._get("GetTitles", Title="Sapiens") == {"titles": [{"title": "Sapiens"}]}
    assert c._get("GetTitles", Title="Sapiens") == {"titles": [{"title": "Sapiens"}]}
    assert len(calls) == 1
    # also across a restart: a new client reads the disk cache
    fresh = NLBClient()
    assert fresh._get("GetTitles", Title="Sapiens") == {"titles": [{"title": "Sapiens"}]} and len(calls) == 1


def test_no_records_is_cached_but_a_failure_is_not(client):
    c, calls, replies = client
    replies.append(httpx.Response(404))
    assert c._get("GetTitles", Title="Nothing") is None
    assert c._get("GetTitles", Title="Nothing") is None and len(calls) == 1
    replies.append(httpx.Response(500))
    assert c._get("GetTitles", Title="Flaky") is None
    assert c._get("GetTitles", Title="Flaky") == {"titles": [{"title": "Sapiens"}]} and len(calls) == 3


def test_a_429_pauses_every_call_instead_of_retrying(client, monkeypatch):
    c, calls, replies = client
    replies.append(httpx.Response(429, headers={"Retry-After": "30"}))
    assert c._get("GetAvailabilityInfo", BRN="1") is None
    assert len(calls) == 1                                 # no retry
    assert c._get("GetTitles", Title="Other") is None and len(calls) == 1   # paused for everything
    monkeypatch.setattr(catalog.time, "monotonic", lambda: c.cooldown_until + 1)
    assert c._get("GetTitles", Title="Other") is not None and len(calls) == 2


def test_over_the_budget_the_call_is_skipped_without_touching_nlb(client):
    c, calls, _ = client
    for i in range(15):
        c._get("GetTitles", Title=f"Book {i}")
    assert len(calls) == 15
    assert c._get("GetTitles", Title="Book 16") is None and len(calls) == 15
