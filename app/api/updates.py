import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, Optional, List

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.application.serializers import normalize_mongo_doc
from app.infrastructure.db.mongo_client import get_mongo_db

try:
    from bson import ObjectId
except Exception:  # pragma: no cover - bson may be unavailable in some envs
    ObjectId = None

router = APIRouter()
log = logging.getLogger("app.updates")


def _mongo_db():
    try:
        return get_mongo_db()
    except Exception:
        log.exception("MongoDB unavailable")
        return None


def _parse_version(value: Optional[str]) -> List[int]:
    if not value:
        return []
    parts = [p for p in re.split(r"[^0-9]+", value) if p != ""]
    return [int(p) for p in parts] if parts else []


def _compare_versions(a: Optional[str], b: Optional[str]) -> int:
    a_parts = _parse_version(a)
    b_parts = _parse_version(b)
    max_len = max(len(a_parts), len(b_parts))
    for i in range(max_len):
        a_val = a_parts[i] if i < len(a_parts) else 0
        b_val = b_parts[i] if i < len(b_parts) else 0
        if a_val < b_val:
            return -1
        if a_val > b_val:
            return 1
    return 0


def _should_show_info(update: Dict[str, Any], app_version: Optional[str]) -> bool:
    if not app_version:
        return True

    max_ver = update.get("max_app_version")
    if max_ver and _compare_versions(app_version, max_ver) > 0:
        return False

    target_ver = update.get("version")
    if target_ver and _compare_versions(app_version, target_ver) >= 0:
        return False

    return True


def _should_show_critical(update: Dict[str, Any], app_version: Optional[str]) -> bool:
    if not app_version:
        return True

    min_ver = update.get("min_app_version")
    if min_ver and _compare_versions(app_version, min_ver) < 0:
        return True

    target_ver = update.get("version")
    if target_ver and _compare_versions(app_version, target_ver) < 0:
        return True

    return False


def _is_critical(update: Dict[str, Any]) -> bool:
    if update.get("force"):
        return True
    severity = str(update.get("severity") or "info").lower()
    return severity == "critical"


async def _active_updates(db) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    query = {
        "is_active": True,
        "$and": [
            {
                "$or": [
                    {"starts_at": {"$lte": now}},
                    {"starts_at": None},
                    {"starts_at": {"$exists": False}},
                ]
            },
            {
                "$or": [
                    {"ends_at": {"$gte": now}},
                    {"ends_at": None},
                    {"ends_at": {"$exists": False}},
                ]
            },
        ],
    }
    cursor = db.app_updates.find(query).sort([("created_at", -1), ("_id", -1)])
    return await cursor.to_list(length=None)


async def _is_acked(db, update_id, device_id: Optional[str], user_id: Optional[str]) -> bool:
    if not update_id or (not device_id and not user_id):
        return False
    query: Dict[str, Any] = {"update_id": update_id}
    if device_id and user_id:
        query["$or"] = [{"device_id": device_id}, {"user_id": user_id}]
    elif device_id:
        query["device_id"] = device_id
    else:
        query["user_id"] = user_id
    return await db.update_ack.find_one(query) is not None


@router.get("/api/updates/latest")
async def get_latest_update(
    app_version: Optional[str] = None,
    device_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    updates = await _active_updates(db)

    for update in updates:
        if not _is_critical(update):
            continue
        if _should_show_critical(update, app_version):
            return JSONResponse(status_code=200, content={"ok": True, "update": normalize_mongo_doc(update)})

    for update in updates:
        if _is_critical(update):
            continue
        if not _should_show_info(update, app_version):
            continue
        if await _is_acked(db, update.get("_id"), device_id, user_id):
            continue
        return JSONResponse(status_code=200, content={"ok": True, "update": normalize_mongo_doc(update)})

    return JSONResponse(status_code=200, content={"ok": True, "update": None})


@router.post("/api/updates/ack")
async def ack_update(request_body: Dict[str, Any]) -> JSONResponse:
    update_id_raw = request_body.get("update_id")
    device_id = request_body.get("device_id")
    user_id = request_body.get("user_id")

    if not update_id_raw:
        raise HTTPException(status_code=400, detail="update_id is required")
    if not device_id and not user_id:
        raise HTTPException(status_code=400, detail="device_id or user_id is required")

    update_id = update_id_raw
    if ObjectId is not None and not isinstance(update_id_raw, ObjectId):
        try:
            update_id = ObjectId(update_id_raw)
        except Exception:
            raise HTTPException(status_code=400, detail="update_id is invalid")

    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    now = datetime.now(timezone.utc)
    filter_doc: Dict[str, Any] = {"update_id": update_id}
    if device_id:
        filter_doc["device_id"] = device_id
    if user_id:
        filter_doc["user_id"] = user_id

    await db.update_ack.update_one(
        filter_doc,
        {"$set": {"acked_at": now}, "$setOnInsert": {"update_id": update_id}},
        upsert=True,
    )

    return JSONResponse(status_code=200, content={"ok": True})
