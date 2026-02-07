from typing import Protocol, List, Dict, Any, Optional


class VideoCatalogCache(Protocol):
    async def get_videos(self) -> Optional[List[Dict[str, Any]]]:
        ...

    async def set_videos(self, videos: List[Dict[str, Any]], ttl_sec: int) -> None:
        ...
