"""Rate limiting: memory store semantics, Redis atomicity under concurrency, fail-closed paths.

Redis tests need a disposable server named by CONCEPTTRAIL_TEST_REDIS_URL (each test uses a
random key prefix and deletes nothing it did not create); they skip when it is not set.
"""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.core.rate_limit import (
    MemoryStore,
    RateLimiterUnavailable,
    RedisStore,
    block_seconds,
    build_store,
    opaque_key,
)
from app.services.auth_service import LoginGuard, LoginThrottled

REDIS_URL = os.environ.get("CONCEPTTRAIL_TEST_REDIS_URL")
needs_redis = pytest.mark.skipif(
    not REDIS_URL, reason="CONCEPTTRAIL_TEST_REDIS_URL is not set; no disposable Redis configured"
)


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_keys_are_opaque_and_normalised() -> None:
    key = opaque_key("login-id", "  Student.One ")
    assert key == opaque_key("login-id", "student.one")
    assert "student" not in key and key.startswith("ct:rl:login-id:")


def test_progressive_cooldown_is_capped() -> None:
    assert [block_seconds(n, 5) for n in (5, 6, 7)] == [60, 120, 240]
    assert block_seconds(30, 5) == 3600


def test_memory_failures_block_then_expire_and_clear() -> None:
    clock = Clock()
    store = MemoryStore(clock=clock)
    for _ in range(3):
        store.record_failure("k", max_failures=3, window=900)
    assert store.blocked_for("k") == 60
    clock.now += 61
    assert store.blocked_for("k") == 0
    store.record_failure("k", 3, 900)  # 4th failure in the same window: longer block
    assert store.blocked_for("k") == 120
    store.clear("k")
    assert store.blocked_for("k") == 0


def test_memory_quota_window() -> None:
    clock = Clock()
    store = MemoryStore(clock=clock)
    assert [store.hit("q", 2, 60) for _ in range(3)] == [0, 0, 60]
    clock.now += 60
    assert store.hit("q", 2, 60) == 0


def test_memory_backend_is_refused_in_production() -> None:
    class S:
        rate_limit_backend = "memory"
        app_env = "production"
        redis_url = None

    with pytest.raises(RateLimiterUnavailable):
        build_store(S())  # type: ignore[arg-type]


class BrokenRedis:
    def register_script(self, _script):
        def run(**_kwargs):
            from redis.exceptions import ConnectionError

            raise ConnectionError("down")

        return run

    def ttl(self, *_args):
        from redis.exceptions import ConnectionError

        raise ConnectionError("down")

    delete = ttl
    ping = ttl


def test_redis_errors_fail_closed() -> None:
    store = RedisStore(BrokenRedis())
    with pytest.raises(RateLimiterUnavailable):
        store.blocked_for("k")
    with pytest.raises(RateLimiterUnavailable):
        store.record_failure("k", 5, 900)
    with pytest.raises(RateLimiterUnavailable):
        store.hit("k", 5, 60)
    assert store.healthy() is False


class Cfg:
    login_max_failures = 3
    login_ip_max_failures = 5
    login_failure_window_seconds = 900


def test_login_guard_throttles_per_identifier_and_per_ip() -> None:
    store = MemoryStore(clock=Clock())
    guard = LoginGuard(lambda: store, lambda: Cfg())
    for _ in range(3):
        guard.failure("alice", "203.0.113.9")
    with pytest.raises(LoginThrottled):
        guard.check("alice", "198.51.100.1")  # the account is blocked from any address
    guard.success("alice")
    guard.check("alice", "198.51.100.1")
    for name in ("bob", "carol"):  # spraying many accounts from one address
        guard.failure(name, "203.0.113.9")
    with pytest.raises(LoginThrottled):
        guard.check("dave", "203.0.113.9")
    guard.check("dave", "198.51.100.1")


@needs_redis
def test_redis_failure_counting_is_atomic_under_concurrency() -> None:
    store = RedisStore.from_url(REDIS_URL)  # type: ignore[arg-type]
    assert store.healthy()
    key = f"ct:rl:test:{uuid.uuid4().hex}"
    with ThreadPoolExecutor(max_workers=16) as pool:
        counts = list(pool.map(lambda _: store.record_failure(key, 50, 120), range(40)))
    assert sorted(counts) == list(range(1, 41))  # no lost or duplicated increments
    assert store.blocked_for(key) == 0
    for _ in range(10):
        store.record_failure(key, 50, 120)
    assert 55 <= store.blocked_for(key) <= 60
    store.clear(key)
    assert store.blocked_for(key) == 0


@needs_redis
def test_redis_quota_is_shared_between_clients() -> None:
    a = RedisStore.from_url(REDIS_URL)  # type: ignore[arg-type]
    b = RedisStore.from_url(REDIS_URL)  # type: ignore[arg-type]  (a second "worker")
    key = f"ct:rl:test:{uuid.uuid4().hex}"
    with ThreadPoolExecutor(max_workers=8) as pool:
        waits = list(pool.map(lambda i: (a if i % 2 else b).hit(key, 10, 60), range(30)))
    assert waits.count(0) == 10 and all(w > 0 for w in waits if w)
    a._r.delete(key)


@needs_redis
def test_redis_recovers_after_an_outage() -> None:
    good = RedisStore.from_url(REDIS_URL)  # type: ignore[arg-type]
    down = RedisStore.from_url("redis://127.0.0.1:1/0")
    with pytest.raises(RateLimiterUnavailable):
        down.blocked_for("k")
    key = f"ct:rl:test:{uuid.uuid4().hex}"
    assert good.hit(key, 1, 60) == 0
    good._r.delete(key)
