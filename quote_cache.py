"""
quote_cache.py — Step 6: Quote-level caching.

Prevents hitting the Claude API repeatedly for the same address + job combination
within a 24-hour window. Separate from area_cache.py (which caches satellite measurements).

Two tiers:
  1. In-memory (instant, cleared on restart)
  2. Redis (persistent, optional — set REDIS_URL in .env)

Cache key: hash of (address + sorted job_ids)
TTL: 24 hours (quotes should refresh daily — condition/weather changes)
"""

import json
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CACHE_TTL_HOURS = 24


def _quote_cache_key(address: str, job_ids: list[str]) -> str:
    """Deterministic cache key from address + sorted job IDs."""
    normalised = address.lower().strip()
    jobs_sorted = ",".join(sorted(job_ids))
    raw = f"quote:{normalised}:{jobs_sorted}"
    return "qcache:" + hashlib.md5(raw.encode()).hexdigest()


class InMemoryQuoteCache:
    def __init__(self):
        self._store: dict[str, tuple[dict, datetime]] = {}

    def get(self, address: str, job_ids: list[str]) -> Optional[dict]:
        key = _quote_cache_key(address, job_ids)
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if datetime.utcnow() > expires_at:
            del self._store[key]
            return None
        return value

    def set(self, address: str, job_ids: list[str], quote_data: dict):
        key = _quote_cache_key(address, job_ids)
        self._store[key] = (
            quote_data,
            datetime.utcnow() + timedelta(hours=CACHE_TTL_HOURS),
        )

    def invalidate(self, address: str, job_ids: list[str]):
        key = _quote_cache_key(address, job_ids)
        self._store.pop(key, None)

    def size(self) -> int:
        return len(self._store)

    def clear_expired(self):
        now = datetime.utcnow()
        expired = [k for k, (_, exp) in self._store.items() if now > exp]
        for k in expired:
            del self._store[k]
        return len(expired)


class RedisQuoteCache:
    def __init__(self):
        import os
        self._client = None
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                import redis
                self._client = redis.from_url(redis_url, decode_responses=True)
                self._client.ping()
                logger.info("Redis quote cache connected")
            except Exception as e:
                logger.warning(f"Redis unavailable for quote cache: {e}")

    def get(self, address: str, job_ids: list[str]) -> Optional[dict]:
        if not self._client:
            return None
        try:
            key = _quote_cache_key(address, job_ids)
            raw = self._client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            logger.warning(f"Redis quote get error: {e}")
            return None

    def set(self, address: str, job_ids: list[str], quote_data: dict):
        if not self._client:
            return
        try:
            key = _quote_cache_key(address, job_ids)
            self._client.setex(key, timedelta(hours=CACHE_TTL_HOURS), json.dumps(quote_data))
        except Exception as e:
            logger.warning(f"Redis quote set error: {e}")

    def invalidate(self, address: str, job_ids: list[str]):
        if not self._client:
            return
        try:
            key = _quote_cache_key(address, job_ids)
            self._client.delete(key)
        except Exception as e:
            logger.warning(f"Redis quote delete error: {e}")

    @property
    def available(self) -> bool:
        return self._client is not None


class QuoteCache:
    """Two-tier quote cache. Redis → in-memory fallback."""

    def __init__(self):
        self._memory = InMemoryQuoteCache()
        self._redis = RedisQuoteCache()

    def get(self, address: str, job_ids: list[str]) -> Optional[dict]:
        result = self._memory.get(address, job_ids)
        if result:
            logger.debug(f"Quote cache HIT (memory): {address[:30]}")
            return result
        result = self._redis.get(address, job_ids)
        if result:
            logger.debug(f"Quote cache HIT (redis): {address[:30]}")
            self._memory.set(address, job_ids, result)
            return result
        return None

    def set(self, address: str, job_ids: list[str], quote_data: dict):
        self._memory.set(address, job_ids, quote_data)
        self._redis.set(address, job_ids, quote_data)

    def invalidate(self, address: str, job_ids: list[str]):
        self._memory.invalidate(address, job_ids)
        self._redis.invalidate(address, job_ids)

    def stats(self) -> dict:
        self._memory.clear_expired()
        return {
            "memory_entries": self._memory.size(),
            "redis_available": self._redis.available,
            "ttl_hours": CACHE_TTL_HOURS,
        }


quote_cache = QuoteCache()
