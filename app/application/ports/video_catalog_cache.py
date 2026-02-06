from typing import Protocol, List, Dict, Any, Optional


class VideoCatalogCache(Protocol):
    def get_videos(self) -> Optional[List[Dict[str, Any]]]:
        ...

    def set_videos(self, videos: List[Dict[str, Any]], ttl_sec: int) -> None:
        ...
