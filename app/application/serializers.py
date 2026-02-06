from datetime import datetime
from typing import Any

try:
    from bson import ObjectId
except Exception:  # pragma: no cover - bson may be unavailable in some envs
    ObjectId = None


def to_json_compatible(value: Any) -> Any:
    if ObjectId is not None and isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: to_json_compatible(v) for k, v in value.items()}
    if isinstance(value, list):
        return [to_json_compatible(v) for v in value]
    if isinstance(value, tuple):
        return [to_json_compatible(v) for v in value]
    return value


def normalize_mongo_doc(doc: dict[str, Any]) -> dict[str, Any]:
    normalized = to_json_compatible(doc)
    if "_id" in normalized:
        normalized["id"] = normalized.pop("_id")
    if "video_id" not in normalized and "id" in normalized:
        normalized["video_id"] = normalized["id"]
    return normalized
