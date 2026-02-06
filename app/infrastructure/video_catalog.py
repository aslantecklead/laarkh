from app.application.video_catalog import ListAvailableVideosUseCase
from app.config import (
    VIDEO_CATALOG_CACHE_KEY,
    VIDEO_CATALOG_CACHE_TTL_SEC,
    VIDEO_CATALOG_COLLECTION,
)
from app.infrastructure.cache.video_catalog_cache import RedisVideoCatalogCache
from app.infrastructure.db.berios_repository import BeriosVideoCatalogRepository


def get_video_catalog_use_case() -> ListAvailableVideosUseCase:
    repository = BeriosVideoCatalogRepository(collection_name=VIDEO_CATALOG_COLLECTION)
    cache = RedisVideoCatalogCache(key=VIDEO_CATALOG_CACHE_KEY)
    return ListAvailableVideosUseCase(repository, cache, ttl_sec=VIDEO_CATALOG_CACHE_TTL_SEC)
