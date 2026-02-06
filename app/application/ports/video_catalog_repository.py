from typing import Protocol, List, Dict, Any


class VideoCatalogRepository(Protocol):
    def list_available_videos(self) -> List[Dict[str, Any]]:
        ...
