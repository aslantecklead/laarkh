import json
from typing import Any, Dict, List, Optional

from app.application.ports.video_catalog_cache import VideoCatalogCache
from app.infrastructure.cache.redis_client import get_redis_client


class RedisVideoCatalogCache(VideoCatalogCache):
    def __init__(self, key: str = "videos:berios:all") -> None:
        self._redis = get_redis_client()
        self._key = key

    def get_videos(self) -> Optional[List[Dict[str, Any]]]:
        cached = self._redis.get(self._key)
        if not cached:
            return None
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", errors="replace")
        try:
            return json.loads(cached)
        except Exception:
            return None

    def set_videos(self, videos: List[Dict[str, Any]], ttl_sec: int) -> None:
        payload = json.dumps(videos, ensure_ascii=False)
        self._redis.setex(self._key, ttl_sec, payload)
