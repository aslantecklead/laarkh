from typing import Any, Dict, List, Tuple

from app.application.ports.video_catalog_repository import VideoCatalogRepository
from app.application.ports.video_catalog_cache import VideoCatalogCache


class ListAvailableVideosUseCase:
    def __init__(self, repository: VideoCatalogRepository, cache: VideoCatalogCache, ttl_sec: int = 600) -> None:
        self._repository = repository
        self._cache = cache
        self._ttl_sec = ttl_sec

    def execute(self, force_refresh: bool = False) -> Tuple[List[Dict[str, Any]], str]:
        cached = self._cache.get_videos()
        if cached is not None and not force_refresh:
            return cached, "cache"

        try:
            videos = self._repository.list_available_videos()
        except Exception:
            if cached is not None:
                return cached, "cache_stale"
            raise

        self._cache.set_videos(videos, self._ttl_sec)
        return videos, "db"
