import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.infrastructure.db.mongo_client import get_mongo_db, ensure_common_user

router = APIRouter()
log = logging.getLogger("app.activity")


def _mongo_db():
    try:
        return get_mongo_db()
    except Exception:
        log.exception("MongoDB unavailable")
        return None


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@router.post("/api/user-activity")
async def log_user_activity(request_body: Dict[str, Any], fastapi_request: Request) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    user_id = request_body.get("user_id") or ensure_common_user()
    now = datetime.now(timezone.utc)

    doc = {
        "user_id": user_id,
        "event": request_body.get("event"),
        "video_id": request_body.get("video_id"),
        "session_id": request_body.get("session_id"),
        "device_id": request_body.get("device_id"),
        "app_version": request_body.get("app_version"),
        "platform": request_body.get("platform"),
        "country": request_body.get("country"),
        "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
        "created_at": now,
        "meta": request_body.get("meta"),
    }
    doc = _drop_none(doc)
    result = db.user_activity_log.insert_one(doc)

    return JSONResponse(status_code=200, content={"ok": True, "id": str(result.inserted_id)})


@router.post("/api/watch/progress")
async def upsert_watch_progress(request_body: Dict[str, Any]) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    user_id = request_body.get("user_id") or ensure_common_user()
    video_id = request_body.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id is required")

    now = datetime.now(timezone.utc)

    progress_doc = {
        "user_id": user_id,
        "video_id": video_id,
        "last_timecode_sec": request_body.get("last_timecode_sec"),
        "last_viewed_at": now,
        "status": request_body.get("status"),
        "subtitle_id": request_body.get("subtitle_id"),
    }
    progress_doc = _drop_none(progress_doc)

    db.watch_progress.update_one(
        {"user_id": user_id, "video_id": video_id},
        {"$set": progress_doc, "$setOnInsert": {"user_id": user_id, "video_id": video_id}},
        upsert=True,
    )

    total_watch_time_sec = request_body.get("total_watch_time_sec")
    if total_watch_time_sec is None:
        total_watch_time_sec = request_body.get("watch_time_sec")
    if total_watch_time_sec is None:
        total_watch_time_sec = request_body.get("last_timecode_sec")

    watched_doc = {
        "user_id": user_id,
        "video_id": video_id,
        "last_watched_at": now,
        "total_watch_time_sec": total_watch_time_sec,
    }
    watched_doc = _drop_none(watched_doc)

    db.user_watched_videos.update_one(
        {"user_id": user_id, "video_id": video_id},
        {"$set": watched_doc, "$setOnInsert": {"user_id": user_id, "video_id": video_id}},
        upsert=True,
    )

    return JSONResponse(status_code=200, content={"ok": True})


@router.get("/api/watch/progress/{video_id}")
async def get_watch_progress(video_id: str, user_id: Optional[str] = None) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    user_id = user_id or ensure_common_user()

    progress = db.watch_progress.find_one({"user_id": user_id, "video_id": video_id})
    watched = db.user_watched_videos.find_one({"user_id": user_id, "video_id": video_id})

    if not progress and not watched:
        raise HTTPException(status_code=404, detail="Progress not found")

    if progress and "_id" in progress:
        progress["_id"] = str(progress["_id"])
    if watched and "_id" in watched:
        watched["_id"] = str(watched["_id"])

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "video_id": video_id,
            "user_id": user_id,
            "watch_progress": progress,
            "user_watched_videos": watched,
        },
    )
