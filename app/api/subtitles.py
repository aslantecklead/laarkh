import os
import json
import logging
import asyncio
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.application.subtitles_job import run_subtitles_job
from app.infrastructure.cache.rate_limit import rate_limit
from app.infrastructure.cache.redis_client import get_redis_client
from app.infrastructure.db.mongo_client import get_mongo_db, ensure_common_user
from app.infrastructure.queue.rq_client import enqueue_subtitle_job


router = APIRouter()
log = logging.getLogger("app.subtitles")


def _extract_video_id(url: str) -> Optional[str]:
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        vid = parsed.path.lstrip("/")
        return vid or None
    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"]:
        return qs["v"][0]
    return None


def _mongo_db():
    try:
        return get_mongo_db()
    except Exception:
        log.exception("MongoDB unavailable")
        return None


def _build_subtitles_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    payload = doc.get("payload")
    if isinstance(payload, dict):
        return payload
    return {
        "text": doc.get("text") or "",
        "language": doc.get("language"),
        "segments": doc.get("segments") or [],
        "meta": doc.get("config") or {},
    }


async def _run_job(url: str, video_id: str, expire_time: int, job_id: str, user_id: str) -> None:
    await run_subtitles_job(url=url, video_id=video_id, expire_time=expire_time, job_id=job_id, user_id=user_id)


@router.post("/api/subtitles")
@rate_limit(by_ip=True)
async def enqueue_subtitles(
    request_body: Dict[str, Any],
    fastapi_request: Request,
) -> JSONResponse:
    redis_client = get_redis_client()
    user_id = await ensure_common_user()

    url = request_body.get("url")
    video_id = request_body.get("video_id")

    if not url:
        raise HTTPException(status_code=400, detail="url is required")

    if not video_id:
        video_id = _extract_video_id(url)

    if not video_id:
        raise HTTPException(status_code=400, detail="Could not extract video_id from url")

    expire_time = int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600))
    status_key = f"status:{video_id}"
    processing_key = f"{video_id}:processing"
    subtitles_key = f"subtitles:{video_id}"

    log.info(
        "[SUBTITLES] enqueue ip=%s video_id=%s url=%s",
        getattr(fastapi_request.client, "host", None),
        video_id,
        url,
    )

    # 1) если уже есть результат — сразу вернём, что готово
    cached = await redis_client.get(subtitles_key)
    if cached:
        return JSONResponse(
            status_code=200,
            content={"ok": True, "video_id": video_id, "status": "done"},
        )

    # 1.1) если есть в MongoDB — прогреем кэш и вернём done
    db = _mongo_db()
    if db is not None:
        doc = await db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            payload = _build_subtitles_payload(doc)
            await redis_client.setex(subtitles_key, expire_time * 2, json.dumps(payload))
            return JSONResponse(
                status_code=200,
                content={"ok": True, "video_id": video_id, "status": "done"},
            )

    # 2) если уже в обработке — вернём processing (НЕ 429)
    if await redis_client.exists(processing_key):
        return JSONResponse(
            status_code=202,
            content={"ok": True, "video_id": video_id, "status": "processing"},
        )

    # 3) ставим лок
    lock_acquired = bool(await redis_client.set(processing_key, "1", ex=expire_time, nx=True))
    if not lock_acquired:
        return JSONResponse(
            status_code=202,
            content={"ok": True, "video_id": video_id, "status": "processing"},
        )

    await redis_client.setex(status_key, expire_time, "processing")
    job_id = __import__("uuid").uuid4().hex

    db = _mongo_db()
    if db is not None:
        now = datetime.now(timezone.utc)
        await db.subtitle_jobs.insert_one(
            {
                "_id": job_id,
                "video_id": video_id,
                "user_id": user_id,
                "status": "processing",
                "requested_at": now,
            }
        )
        await db.videos.update_one(
            {"video_id": video_id},
            {
                "$setOnInsert": {
                    "video_id": video_id,
                    "source_url": url,
                    "created_at": now,
                    "added_by_user_id": user_id,
                    "added_at": now,
                    "is_public": True,
                }
            },
            upsert=True,
        )

    try:
        enqueue_subtitle_job(url=url, video_id=video_id, expire_time=expire_time, job_id=job_id, user_id=user_id)
    except Exception:
        log.exception("Failed to enqueue subtitle job; falling back to in-process task")
        asyncio.create_task(
            _run_job(url=url, video_id=video_id, expire_time=expire_time, job_id=job_id, user_id=user_id)
        )

    return JSONResponse(
        status_code=202,
        content={"ok": True, "video_id": video_id, "status": "processing"},
    )


@router.get("/api/subtitles/{video_id}/status")
async def get_status(video_id: str) -> Dict[str, Any]:
    redis_client = get_redis_client()

    status_key = f"status:{video_id}"
    processing_key = f"{video_id}:processing"
    subtitles_key = f"subtitles:{video_id}"

    status = await redis_client.get(status_key)
    if status:
        if isinstance(status, bytes):
            status = status.decode("utf-8", errors="replace")
        return {"ok": True, "video_id": video_id, "status": status}

    # fallback, если статус не записан, но ключи есть
    if await redis_client.get(subtitles_key):
        return {"ok": True, "video_id": video_id, "status": "done"}

    db = _mongo_db()
    if db is not None:
        doc = await db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            return {"ok": True, "video_id": video_id, "status": "done"}

    if await redis_client.exists(processing_key):
        return {"ok": True, "video_id": video_id, "status": "processing"}

    return {"ok": False, "video_id": video_id, "status": "not_found"}


@router.get("/api/subtitles/{video_id}")
async def get_subtitles(video_id: str) -> JSONResponse:
    redis_client = get_redis_client()

    processing_key = f"{video_id}:processing"
    subtitles_key = f"subtitles:{video_id}"

    cached = await redis_client.get(subtitles_key)
    if cached:
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", errors="replace")
        return JSONResponse(
            status_code=200,
            content={"ok": True, "video_id": video_id, "subtitles": json.loads(cached)},
        )

    db = _mongo_db()
    if db is not None:
        doc = await db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            payload = _build_subtitles_payload(doc)
            await redis_client.setex(
                subtitles_key,
                int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600)) * 2,
                json.dumps(payload),
            )
            return JSONResponse(
                status_code=200,
                content={"ok": True, "video_id": video_id, "subtitles": payload},
            )

    if await redis_client.exists(processing_key):
        return JSONResponse(
            status_code=202,
            content={"ok": True, "video_id": video_id, "detail": "processing"},
        )

    raise HTTPException(status_code=404, detail="Subtitles not found")
