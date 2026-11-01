"""Rate limiting with a shared backend for production and a per-process one for development.

Two primitives, both keyed by an opaque string (callers pass hashes, never raw identifiers):

- failure throttling: `record_failure` counts failures in a window; at `max_failures` the key is
  blocked with a progressive cooldown (60 s, 120 s, 240 s ... capped at one hour), and
  `blocked_for` reports the remaining block; `clear` resets it after a success;
- request quotas: `hit` counts requests in a fixed window and returns the seconds to wait once
  the limit is exceeded (0 while allowed).

`RedisStore` performs each operation in one Lua script, so counters are atomic across workers
and containers. Any Redis error raises `RateLimiterUnavailable`; callers fail closed. The memory
store is refused when APP_ENV=production (settings validation requires the Redis backend).
"""

from __future__ import annotations

import hashlib
import math
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from app.core.config import Settings, get_settings

MAX_BLOCK_SECONDS = 3600
BASE_BLOCK_SECONDS = 60


class RateLimiterUnavailable(Exception):
    """The configured limiter cannot be reached; protected operations must be refused."""


def opaque_key(namespace: str, value: str) -> str:
    digest = hashlib.sha256(value.strip().casefold().encode()).hexdigest()[:32]
    return f"ct:rl:{namespace}:{digest}"


def block_seconds(failures: int, max_failures: int) -> int:
    return min(MAX_BLOCK_SECONDS, BASE_BLOCK_SECONDS * 2 ** max(0, failures - max_failures))


class RateLimitStore(Protocol):
    def blocked_for(self, key: str) -> int: ...
    def record_failure(self, key: str, max_failures: int, window: int) -> int: ...
    def clear(self, key: str) -> None: ...
    def hit(self, key: str, limit: int, window: int) -> int: ...
    def healthy(self) -> bool: ...


@dataclass
class _Entry:
    count: int
    window_started: float
    blocked_until: float = 0.0


class MemoryStore:
    """Thread-safe, single-process; for development and tests only."""

    def __init__(self, clock=time.monotonic, max_keys: int = 10_000) -> None:
        self._clock = clock
        self._max_keys = max_keys
        self._failures: dict[str, _Entry] = {}
        self._hits: dict[str, _Entry] = {}
        self._lock = threading.Lock()

    def _bound(self, table: dict[str, _Entry]) -> None:
        if len(table) > self._max_keys:  # bound memory under many distinct keys
            table.pop(next(iter(table)), None)

    def blocked_for(self, key: str) -> int:
        now = self._clock()
        with self._lock:
            entry = self._failures.get(key)
            if entry and now < entry.blocked_until:
                return max(1, math.ceil(entry.blocked_until - now))
            return 0

    def record_failure(self, key: str, max_failures: int, window: int) -> int:
        now = self._clock()
        with self._lock:
            entry = self._failures.get(key)
            if entry is None or (
                now - entry.window_started >= window and now >= entry.blocked_until
            ):
                entry = _Entry(0, now)
            entry.count += 1
            if entry.count >= max_failures:
                entry.blocked_until = now + block_seconds(entry.count, max_failures)
            self._failures[key] = entry
            self._bound(self._failures)
            return entry.count

    def clear(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)

    def hit(self, key: str, limit: int, window: int) -> int:
        now = self._clock()
        with self._lock:
            entry = self._hits.get(key)
            if entry is None or now - entry.window_started >= window:
                entry = _Entry(0, now)
            entry.count += 1
            self._hits[key] = entry
            self._bound(self._hits)
            if entry.count > limit:
                return max(1, math.ceil(entry.window_started + window - now))
            return 0

    def healthy(self) -> bool:
        return True


# KEYS[1] failure counter, KEYS[2] block marker; ARGV max_failures, window, base, cap.
_FAILURE_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
local maxf = tonumber(ARGV[1])
if n >= maxf then
  local secs = math.min(tonumber(ARGV[4]), tonumber(ARGV[3]) * (2 ^ (n - maxf)))
  redis.call('SET', KEYS[2], '1', 'EX', math.floor(secs))
  if redis.call('TTL', KEYS[1]) < secs then redis.call('EXPIRE', KEYS[1], math.floor(secs)) end
end
return n
"""

# KEYS[1] counter; ARGV limit, window. Returns seconds to wait (0 while allowed).
_HIT_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 then redis.call('EXPIRE', KEYS[1], ARGV[2]) end
if n > tonumber(ARGV[1]) then
  local ttl = redis.call('TTL', KEYS[1])
  if ttl < 1 then ttl = 1 end
  return ttl
end
return 0
"""


class RedisStore:
    """Shared, atomic counters in Redis (one Lua script per operation)."""

    def __init__(self, client) -> None:  # a redis.Redis instance (or a compatible fake)
        self._r = client
        self._failure = client.register_script(_FAILURE_LUA)
        self._hit = client.register_script(_HIT_LUA)

    @classmethod
    def from_url(cls, url: str) -> RedisStore:
        import redis

        return cls(
            redis.Redis.from_url(
                url, socket_timeout=0.5, socket_connect_timeout=0.5, health_check_interval=30
            )
        )

    def _call(self, fn, *args, **kwargs):
        from redis.exceptions import RedisError

        try:
            return fn(*args, **kwargs)
        except RedisError as exc:
            raise RateLimiterUnavailable(type(exc).__name__) from None

    def blocked_for(self, key: str) -> int:
        ttl = self._call(self._r.ttl, f"{key}:block")
        return int(ttl) if ttl and int(ttl) > 0 else 0

    def record_failure(self, key: str, max_failures: int, window: int) -> int:
        return int(
            self._call(
                self._failure,
                keys=[key, f"{key}:block"],
                args=[max_failures, window, BASE_BLOCK_SECONDS, MAX_BLOCK_SECONDS],
            )
        )

    def clear(self, key: str) -> None:
        self._call(self._r.delete, key, f"{key}:block")

    def hit(self, key: str, limit: int, window: int) -> int:
        return int(self._call(self._hit, keys=[key], args=[limit, window]))

    def healthy(self) -> bool:
        try:
            return bool(self._call(self._r.ping))
        except RateLimiterUnavailable:
            return False


def build_store(settings: Settings) -> RateLimitStore:
    if settings.rate_limit_backend == "redis":
        if settings.redis_url is None:
            raise RateLimiterUnavailable("redis_url_missing")
        return RedisStore.from_url(settings.redis_url.get_secret_value())
    if settings.app_env == "production":
        raise RateLimiterUnavailable("memory_backend_refused_in_production")
    return MemoryStore()


@lru_cache(maxsize=1)
def get_store() -> RateLimitStore:
    return build_store(get_settings())
