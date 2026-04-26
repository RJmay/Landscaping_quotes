"""
area_cache.py — Cache for satellite area analysis results.

Prevents re-calling the Maps API for the same address within 7 days.
Two tiers: in-memory (fast, lost on restart) + Redis (optional, persistent).
"""

import json
import os
import hashlib
import logging
from datetime import datetime, timedelta
from typing import Optional
from dataclasses import asdict

from maps_agent import AreaAnalysis

logger = logging.getLogger(__name__)

CACHE_TTL_DAYS = 7


# ─── Key + serialisation ──────────────────────────────────────────────────────

def _cache_key(address: str) -> str:
    normalised = address.lower().strip().replace(", australia", "").replace(", au", "")
    return "area:" + hashlib.md5(normalised.encode()).hexdigest()


def _serialise(analysis: AreaAnalysis) -> str:
    return json.dumps(asdict(analysis))


def _deserialise(data: str) -> AreaAnalysis:
    d = json.loads(data)
    # Remove the computed property 'driveway_sqm' if it was accidentally serialised
    d.pop("driveway_sqm", None)
    return AreaAnalysis(**d)


# ─── In-memory cache ──────────────────────────────────────────────────────────

class InMemoryCache:
    def __init__(self):
        self._store: dict[str, tuple[str, datetime]] = {}

    def get(self, key: str) -> Optional[AreaAnalysis]:
        if key not in self._store:
            return None
        value, expires_at = self._store[key]
        if datetime.utcnow() > expires_at:
            del self._store[key]
            return None
        try:
            return _deserialise(value)
        except Exception as e:
            logger.warning(f"Cache deserialise error: {e}")
            del self._store[key]
            return None

    def set(self, key: str, analysis: AreaAnalysis, ttl_days: int = CACHE_TTL_DAYS):
        self._store[key] = (
            _serialise(analysis),
            datetime.utcnow() + timedelta(days=ttl_days),
        )

    def delete(self, key: str):
        self._store.pop(key, None)

    def size(self) -> int:
        return len(self._store)


# ─── Redis cache (optional) ───────────────────────────────────────────────────

class RedisCache:
    def __init__(self):
        self._client = None
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            try:
                import redis
                self._client = redis.from_url(redis_url, decode_responses=True)
                self._client.ping()
                logger.info("Redis area cache connected")
            except Exception as e:
                logger.warning(f"Redis unavailable: {e}")

    def get(self, key: str) -> Optional[AreaAnalysis]:
        if not self._client:
            return None
        try:
            value = self._client.get(key)
            return _deserialise(value) if value else None
        except Exception as e:
            logger.warning(f"Redis get error: {e}")
            return None

    def set(self, key: str, analysis: AreaAnalysis, ttl_days: int = CACHE_TTL_DAYS):
        if not self._client:
            return
        try:
            self._client.setex(key, timedelta(days=ttl_days), _serialise(analysis))
        except Exception as e:
            logger.warning(f"Redis set error: {e}")

    def delete(self, key: str):
        if not self._client:
            return
        try:
            self._client.delete(key)
        except Exception:
            pass

    @property
    def available(self) -> bool:
        return self._client is not None


# ─── Unified cache facade ─────────────────────────────────────────────────────

class AreaAnalysisCache:
    def __init__(self):
        self._memory = InMemoryCache()
        self._redis = RedisCache()

    def get(self, address: str) -> Optional[AreaAnalysis]:
        key = _cache_key(address)
        result = self._memory.get(key)
        if result:
            logger.debug(f"Area cache HIT (memory): {address[:40]}")
            return result
        result = self._redis.get(key)
        if result:
            logger.debug(f"Area cache HIT (redis): {address[:40]}")
            self._memory.set(key, result)
            return result
        logger.debug(f"Area cache MISS: {address[:40]}")
        return None

    def set(self, address: str, analysis: AreaAnalysis):
        key = _cache_key(address)
        self._memory.set(key, analysis)
        self._redis.set(key, analysis)

    def invalidate(self, address: str):
        key = _cache_key(address)
        self._memory.delete(key)
        self._redis.delete(key)

    def stats(self) -> dict:
        return {
            "memory_entries": self._memory.size(),
            "redis_available": self._redis.available,
        }


# ─── Singleton ────────────────────────────────────────────────────────────────
area_cache = AreaAnalysisCache()
