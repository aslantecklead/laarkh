import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.application.serializers import normalize_mongo_doc
from app.infrastructure.db.mongo_client import (
    IdentityResolutionError,
    ensure_user,
    get_test_user_ids,
    get_mongo_db,
    resolve_identity,
)

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


def _parse_iso_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid datetime format (use ISO 8601)")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _resolve_user_identity(request_body: Dict[str, Any]) -> Dict[str, Optional[str]]:
    try:
        return await resolve_identity(
            user_id=request_body.get("user_id"),
            device_id=request_body.get("device_id"),
            session_id=request_body.get("session_id"),
            touch_session=True,
        )
    except IdentityResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/api/user-activity")
async def list_user_activity(
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    event: Optional[str] = None,
    video_id: Optional[str] = None,
    since: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    try:
        identity = await resolve_identity(
            user_id=user_id,
            device_id=device_id,
            session_id=session_id,
            touch_session=False,
        )
    except IdentityResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    resolved_user_id = identity["user_id"]
    if not resolved_user_id:
        raise HTTPException(status_code=400, detail="user_id or device_id or session_id is required")

    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    filter_doc: Dict[str, Any] = {"user_id": resolved_user_id}
    if session_id:
        filter_doc["session_id"] = session_id
    if event:
        filter_doc["event"] = event
    if video_id:
        filter_doc["video_id"] = video_id
    since_dt = _parse_iso_datetime(since)
    if since_dt is not None:
        filter_doc["created_at"] = {"$gte": since_dt}

    cursor = db.user_activity_log.find(filter_doc).sort([("created_at", -1), ("_id", -1)]).limit(limit)
    docs = await cursor.to_list(length=limit)
    items = [normalize_mongo_doc(doc) for doc in docs]

    return JSONResponse(status_code=200, content={"ok": True, "count": len(items), "items": items})


@router.get("/api/stats/overview")
async def get_stats_overview(
    exclude_test: bool = True,
    include_public: bool = True,
) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    excluded_user_ids = set()
    if exclude_test:
        excluded_user_ids = await get_test_user_ids(include_public=include_public)

    users_filter: Dict[str, Any] = {}
    related_filter: Dict[str, Any] = {}
    if excluded_user_ids:
        users_filter["_id"] = {"$nin": list(excluded_user_ids)}
        related_filter["user_id"] = {"$nin": list(excluded_user_ids)}

    users_count = await db.users.count_documents(users_filter)
    user_stats_count = await db.user_stats.count_documents({"_id": users_filter.get("_id", {"$exists": True})})
    activity_events_count = await db.user_activity_log.count_documents(related_filter)
    watched_videos_count = await db.user_watched_videos.count_documents(related_filter)
    subtitle_jobs_count = await db.subtitle_jobs.count_documents(related_filter)

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "exclude_test": exclude_test,
            "include_public": include_public,
            "excluded_user_ids": sorted(excluded_user_ids),
            "totals": {
                "users": users_count,
                "user_stats": user_stats_count,
                "activity_events": activity_events_count,
                "watched_videos": watched_videos_count,
                "subtitle_jobs": subtitle_jobs_count,
            },
        },
    )


@router.post("/api/user-activity")
async def log_user_activity(request_body: Dict[str, Any], fastapi_request: Request) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    identity = await _resolve_user_identity(request_body)
    user_id = identity["user_id"]
    device_id = identity["device_id"]
    session_id = identity.get("session_id")
    now = datetime.now(timezone.utc)

    await ensure_user(
        user_id=user_id,
        device_id=device_id,
        meta={
            "session_id": session_id or request_body.get("session_id"),
            "locale": request_body.get("locale"),
            "timezone": request_body.get("timezone"),
            "app_version": request_body.get("app_version"),
            "platform": request_body.get("platform"),
            "country": request_body.get("country"),
            "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
        },
    )

    doc = {
        "user_id": user_id,
        "event": request_body.get("event"),
        "video_id": request_body.get("video_id"),
        "session_id": session_id or request_body.get("session_id"),
        "device_id": device_id,
        "app_version": request_body.get("app_version"),
        "platform": request_body.get("platform"),
        "country": request_body.get("country"),
        "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
        "created_at": now,
        "meta": request_body.get("meta"),
    }
    doc = _drop_none(doc)
    result = await db.user_activity_log.insert_one(doc)

    return JSONResponse(status_code=200, content={"ok": True, "id": str(result.inserted_id)})


@router.post("/api/watch/progress")
async def upsert_watch_progress(request_body: Dict[str, Any]) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    identity = await _resolve_user_identity(request_body)
    user_id = identity["user_id"]
    device_id = identity["device_id"]
    session_id = identity.get("session_id")
    video_id = request_body.get("video_id")
    if not video_id:
        raise HTTPException(status_code=400, detail="video_id is required")

    now = datetime.now(timezone.utc)

    await ensure_user(
        user_id=user_id,
        device_id=device_id,
        meta={
            "session_id": session_id or request_body.get("session_id"),
            "locale": request_body.get("locale"),
            "timezone": request_body.get("timezone"),
            "app_version": request_body.get("app_version"),
            "platform": request_body.get("platform"),
            "country": request_body.get("country"),
        },
    )

    progress_doc = {
        "user_id": user_id,
        "video_id": video_id,
        "last_timecode_sec": request_body.get("last_timecode_sec"),
        "last_viewed_at": now,
        "status": request_body.get("status"),
        "subtitle_id": request_body.get("subtitle_id"),
    }
    progress_doc = _drop_none(progress_doc)

    await db.watch_progress.update_one(
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

    await db.user_watched_videos.update_one(
        {"user_id": user_id, "video_id": video_id},
        {"$set": watched_doc, "$setOnInsert": {"user_id": user_id, "video_id": video_id}},
        upsert=True,
    )

    return JSONResponse(status_code=200, content={"ok": True})


@router.get("/api/watch/progress/{video_id}")
async def get_watch_progress(
    video_id: str,
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    try:
        identity = await resolve_identity(
            user_id=user_id,
            device_id=device_id,
            session_id=session_id,
            touch_session=True,
        )
    except IdentityResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    user_id = identity["user_id"]

    progress = await db.watch_progress.find_one({"user_id": user_id, "video_id": video_id})
    watched = await db.user_watched_videos.find_one({"user_id": user_id, "video_id": video_id})

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


@router.get("/api/watch/progress")
async def list_watch_progress(
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    try:
        identity = await resolve_identity(
            user_id=user_id,
            device_id=device_id,
            session_id=session_id,
            touch_session=False,
        )
    except IdentityResolutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    resolved_user_id = identity["user_id"]

    if limit < 1:
        limit = 1
    if limit > 500:
        limit = 500

    filter_doc: Dict[str, Any] = {"user_id": resolved_user_id}
    if status:
        filter_doc["status"] = status

    cursor = db.watch_progress.find(filter_doc).sort([("last_viewed_at", -1), ("_id", -1)]).limit(limit)
    docs = await cursor.to_list(length=limit)
    items = [normalize_mongo_doc(doc) for doc in docs]

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "user_id": resolved_user_id,
            "count": len(items),
            "items": items,
        },
    )
