import logging
from typing import Any, Dict, List

from app.application.ports.video_catalog_repository import VideoCatalogRepository
from app.application.serializers import normalize_mongo_doc
from app.infrastructure.db.mongo_client import get_mongo_db

log = logging.getLogger("app.berios_repo")


class BeriosVideoCatalogRepository(VideoCatalogRepository):
    def __init__(self, collection_name: str = "Berios") -> None:
        self._collection_name = collection_name

    def list_available_videos(self) -> List[Dict[str, Any]]:
        db = get_mongo_db()
        collection = db[self._collection_name]
        cursor = collection.find({})
        try:
            cursor = cursor.sort([("updated_at", -1), ("created_at", -1), ("_id", -1)])
        except Exception:
            pass
        return [normalize_mongo_doc(doc) for doc in cursor]
