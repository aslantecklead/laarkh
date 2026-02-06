import os
import json
import logging
import asyncio
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

from fastapi import APIRouter, HTTPException, Request, Body
from fastapi.responses import JSONResponse

from app.application.use_cases import GenerateSubtitlesUseCase
from app.infrastructure.cache.rate_limit import rate_limit
from app.infrastructure.cache.redis_client import get_redis_client
from app.infrastructure.db.mongo_client import get_mongo_db, ensure_common_user

from app.config import (
    TRANSLATION_AUTO_DOWNLOAD,
    TRANSLATION_DEFAULT_TARGET_LANGUAGE,
)
from app.infrastructure.translation.argos_translate import ArgosTranslateError, get_argos_translator

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


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def _run_job(url: str, video_id: str, expire_time: int, job_id: str, user_id: str) -> None:
    redis_client = get_redis_client()

    status_key = f"status:{video_id}"
    processing_key = f"{video_id}:processing"
    subtitles_key = f"subtitles:{video_id}"

    try:
        use_case = GenerateSubtitlesUseCase()

        result = await use_case.execute(url, video_id)
        subtitles = result.get("subtitles")
        if subtitles is None:
            raise RuntimeError("use_case returned no subtitles")

        db = _mongo_db()
        if db is not None:
            now = datetime.now(timezone.utc)
            # Upsert video metadata
            db.videos.update_one(
                {"video_id": video_id},
                {
                    "$setOnInsert": {
                        "video_id": video_id,
                        "source_url": url,
                        "created_at": now,
                        "added_by_user_id": user_id,
                        "added_at": now,
                        "is_public": True,
                    },
                    "$set": {
                        "title": result.get("title"),
                        "uploader": result.get("uploader"),
                        "duration_sec": result.get("duration"),
                        "updated_at": now,
                    },
                },
                upsert=True,
            )

            subtitles_payload = json.dumps(subtitles, ensure_ascii=False)
            content_hash = hashlib.md5(subtitles_payload.encode("utf-8")).hexdigest()

            subtitle_doc = {
                "video_id": video_id,
                "user_id": user_id,
                "job_id": job_id,
                "generated_at": now,
                "format": "json",
                "text": subtitles.get("text"),
                "segments": subtitles.get("segments"),
                "payload": subtitles,
                "config": {
                    "asr_model": (subtitles.get("meta") or {}).get("model"),
                    "model_version": (subtitles.get("meta") or {}).get("engine"),
                    "language": subtitles.get("language"),
                    "sample_rate": None,
                    "channels": None,
                },
                "language": subtitles.get("language"),
                "version": 1,
                "size_bytes": len(subtitles_payload.encode("utf-8")),
                "content_hash": content_hash,
                "pipeline_version": "v1",
                "quality_score": None,
                "diarization": None,
                "word_timestamps": None,
            }
            subtitle_doc["config"] = _drop_none(subtitle_doc["config"])
            subtitle_doc = _drop_none(subtitle_doc)
            subtitle_insert = db.subtitles.insert_one(subtitle_doc)

            db.subtitle_jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "finished_at": now,
                        "runtime_sec": None,
                        "subtitle_id": subtitle_insert.inserted_id,
                    }
                },
            )

        redis_client.setex(subtitles_key, expire_time * 2, json.dumps(subtitles))
        redis_client.setex(status_key, expire_time, "done")

        log.info("[JOB] done video_id=%s", video_id)

    except Exception as e:
        log.exception("[JOB] error video_id=%s: %s", video_id, e)
        db = _mongo_db()
        if db is not None:
            db.subtitle_jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "error",
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": str(e),
                    }
                },
            )
        try:
            redis_client.setex(status_key, expire_time, "error")
        except Exception:
            pass
    finally:
        # Снимаем лок в конце job
        try:
            redis_client.delete(processing_key)
        except Exception:
            pass


@router.post("/api/subtitles")
@rate_limit(by_ip=True)
async def enqueue_subtitles(
    request_body: Dict[str, Any],
    fastapi_request: Request,
) -> JSONResponse:
    redis_client = get_redis_client()
    user_id = ensure_common_user()

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
    cached = redis_client.get(subtitles_key)
    if cached:
        return JSONResponse(
            status_code=200,
            content={"ok": True, "video_id": video_id, "status": "done"},
        )

    # 1.1) если есть в MongoDB — прогреем кэш и вернём done
    db = _mongo_db()
    if db is not None:
        doc = db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            payload = _build_subtitles_payload(doc)
            redis_client.setex(subtitles_key, expire_time * 2, json.dumps(payload))
            return JSONResponse(
                status_code=200,
                content={"ok": True, "video_id": video_id, "status": "done"},
            )

    # 2) если уже в обработке — вернём processing (НЕ 429)
    if redis_client.exists(processing_key):
        return JSONResponse(
            status_code=202,
            content={"ok": True, "video_id": video_id, "status": "processing"},
        )

    # 3) ставим лок
    lock_acquired = bool(redis_client.set(processing_key, "1", ex=expire_time, nx=True))
    if not lock_acquired:
        return JSONResponse(
            status_code=202,
            content={"ok": True, "video_id": video_id, "status": "processing"},
        )

    redis_client.setex(status_key, expire_time, "processing")
    job_id = __import__("uuid").uuid4().hex

    db = _mongo_db()
    if db is not None:
        now = datetime.now(timezone.utc)
        db.subtitle_jobs.insert_one(
            {
                "_id": job_id,
                "video_id": video_id,
                "user_id": user_id,
                "status": "processing",
                "requested_at": now,
            }
        )
        db.videos.update_one(
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

    status = redis_client.get(status_key)
    if status:
        if isinstance(status, bytes):
            status = status.decode("utf-8", errors="replace")
        return {"ok": True, "video_id": video_id, "status": status}

    # fallback, если статус не записан, но ключи есть
    if redis_client.get(subtitles_key):
        return {"ok": True, "video_id": video_id, "status": "done"}

    db = _mongo_db()
    if db is not None:
        doc = db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            return {"ok": True, "video_id": video_id, "status": "done"}

    if redis_client.exists(processing_key):
        return {"ok": True, "video_id": video_id, "status": "processing"}

    return {"ok": False, "video_id": video_id, "status": "not_found"}


@router.get("/api/subtitles/{video_id}")
async def get_subtitles(video_id: str) -> JSONResponse:
    redis_client = get_redis_client()

    processing_key = f"{video_id}:processing"
    subtitles_key = f"subtitles:{video_id}"

    cached = redis_client.get(subtitles_key)
    if cached:
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", errors="replace")
        return JSONResponse(
            status_code=200,
            content={"ok": True, "video_id": video_id, "subtitles": json.loads(cached)},
        )

    db = _mongo_db()
    if db is not None:
        doc = db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            payload = _build_subtitles_payload(doc)
            redis_client.setex(subtitles_key, int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600)) * 2, json.dumps(payload))
            return JSONResponse(
                status_code=200,
                content={"ok": True, "video_id": video_id, "subtitles": payload},
            )

    if redis_client.exists(processing_key):
        return JSONResponse(
            status_code=202,
            content={"ok": True, "video_id": video_id, "detail": "processing"},
        )

    raise HTTPException(status_code=404, detail="Subtitles not found")


def _translation_keys(video_id: str, target_language: str):
    lang = (target_language or TRANSLATION_DEFAULT_TARGET_LANGUAGE or "ru").strip().lower()
    data_key = f"translation:{video_id}:{lang}"
    status_key = f"translation_status:{video_id}:{lang}"
    processing_key = f"translation_processing:{video_id}:{lang}"
    return data_key, status_key, processing_key


def _build_translation_payload(doc: Dict[str, Any]) -> Dict[str, Any]:
    payload = doc.get("payload")
    if isinstance(payload, dict):
        return payload
    return {
        "text": doc.get("text") or "",
        "language": doc.get("language"),
        "segments": doc.get("segments") or [],
        "meta": doc.get("meta") or {},
    }


def _load_subtitles_payload(video_id: str) -> Optional[Dict[str, Any]]:
    redis_client = get_redis_client()
    subtitles_key = f"subtitles:{video_id}"
    cached = redis_client.get(subtitles_key)
    if cached:
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", errors="replace")
        return json.loads(cached)

    db = _mongo_db()
    if db is not None:
        doc = db.subtitles.find_one({"video_id": video_id}, sort=[("generated_at", -1)])
        if doc:
            payload = _build_subtitles_payload(doc)
            expire_time = int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600))
            redis_client.setex(subtitles_key, expire_time * 2, json.dumps(payload, ensure_ascii=False))
            return payload

    return None


def _load_translation_payload(video_id: str, target_language: str) -> Optional[Dict[str, Any]]:
    redis_client = get_redis_client()
    data_key, _, _ = _translation_keys(video_id, target_language)
    cached = redis_client.get(data_key)
    if cached:
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", errors="replace")
        return json.loads(cached)

    db = _mongo_db()
    if db is not None:
        doc = db.subtitle_translations.find_one(
            {"video_id": video_id, "target_language": (target_language or "").lower()},
            sort=[("generated_at", -1)],
        )
        if doc:
            payload = _build_translation_payload(doc)
            expire_time = int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600))
            redis_client.setex(data_key, expire_time * 2, json.dumps(payload, ensure_ascii=False))
            return payload

    return None


async def _run_translation_job(
    *,
    video_id: str,
    target_language: str,
    source_language: Optional[str],
    expire_time: int,
    job_id: str,
    user_id: str,
) -> None:
    redis_client = get_redis_client()
    data_key, status_key, processing_key = _translation_keys(video_id, target_language)

    try:
        subtitles_payload = _load_subtitles_payload(video_id)
        if not subtitles_payload:
            raise RuntimeError("Subtitles not found")

        translator = get_argos_translator(auto_download=TRANSLATION_AUTO_DOWNLOAD)
        translation_payload = translator.translate_subtitles(
            subtitles_payload,
            target_language=target_language,
            source_language=source_language,
        )

        db = _mongo_db()
        if db is not None:
            now = datetime.now(timezone.utc)
            translation_json = json.dumps(translation_payload, ensure_ascii=False)
            content_hash = hashlib.md5(translation_json.encode("utf-8")).hexdigest()

            translation_doc = {
                "video_id": video_id,
                "user_id": user_id,
                "job_id": job_id,
                "generated_at": now,
                "format": "json",
                "text": translation_payload.get("text"),
                "segments": translation_payload.get("segments"),
                "payload": translation_payload,
                "meta": translation_payload.get("meta"),
                "source_language": source_language,
                "target_language": target_language,
                "language": target_language,
                "version": 1,
                "size_bytes": len(translation_json.encode("utf-8")),
                "content_hash": content_hash,
                "pipeline_version": "v1",
            }
            translation_doc = _drop_none(translation_doc)
            translation_insert = db.subtitle_translations.insert_one(translation_doc)

            db.subtitle_translation_jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "done",
                        "finished_at": now,
                        "runtime_sec": None,
                        "translation_id": translation_insert.inserted_id,
                    }
                },
            )

        redis_client.setex(data_key, expire_time * 2, json.dumps(translation_payload, ensure_ascii=False))
        redis_client.setex(status_key, expire_time, "done")
        log.info("[TRANSLATION] done video_id=%s target=%s", video_id, target_language)

    except ArgosTranslateError as e:
        log.exception("[TRANSLATION] argos error video_id=%s target=%s: %s", video_id, target_language, e)
        db = _mongo_db()
        if db is not None:
            db.subtitle_translation_jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "error",
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": str(e),
                    }
                },
            )
        try:
            redis_client.setex(status_key, expire_time, "error")
        except Exception:
            pass
    except Exception as e:
        log.exception("[TRANSLATION] error video_id=%s target=%s: %s", video_id, target_language, e)
        db = _mongo_db()
        if db is not None:
            db.subtitle_translation_jobs.update_one(
                {"_id": job_id},
                {
                    "$set": {
                        "status": "error",
                        "finished_at": datetime.now(timezone.utc),
                        "error_message": str(e),
                    }
                },
            )
        try:
            redis_client.setex(status_key, expire_time, "error")
        except Exception:
            pass
    finally:
        try:
            redis_client.delete(processing_key)
        except Exception:
            pass


@router.post("/api/subtitles/{video_id}/translation")
async def enqueue_translation(
    video_id: str,
    request_body: Dict[str, Any] = Body(default_factory=dict),
    fastapi_request: Request = None,
) -> JSONResponse:
    redis_client = get_redis_client()
    user_id = ensure_common_user()

    target_language = (request_body.get("target_language") or TRANSLATION_DEFAULT_TARGET_LANGUAGE or "ru").strip().lower()
    source_language = request_body.get("source_language")
    if source_language:
        source_language = source_language.strip().lower()

    if not target_language:
        raise HTTPException(status_code=400, detail="target_language is required")

    data_key, status_key, processing_key = _translation_keys(video_id, target_language)
    expire_time = int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600))

    log.info(
        "[TRANSLATION] enqueue ip=%s video_id=%s target=%s",
        getattr(getattr(fastapi_request, "client", None), "host", None),
        video_id,
        target_language,
    )

    cached = redis_client.get(data_key)
    if cached:
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "video_id": video_id,
                "target_language": target_language,
                "status": "done",
            },
        )

    db = _mongo_db()
    if db is not None:
        doc = db.subtitle_translations.find_one(
            {"video_id": video_id, "target_language": target_language},
            sort=[("generated_at", -1)],
        )
        if doc:
            payload = _build_translation_payload(doc)
            redis_client.setex(data_key, expire_time * 2, json.dumps(payload, ensure_ascii=False))
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "video_id": video_id,
                    "target_language": target_language,
                    "status": "done",
                },
            )

    if redis_client.exists(processing_key):
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "video_id": video_id,
                "target_language": target_language,
                "status": "processing",
            },
        )

    if not _load_subtitles_payload(video_id):
        raise HTTPException(status_code=404, detail="Subtitles not found")

    lock_acquired = bool(redis_client.set(processing_key, "1", ex=expire_time, nx=True))
    if not lock_acquired:
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "video_id": video_id,
                "target_language": target_language,
                "status": "processing",
            },
        )

    redis_client.setex(status_key, expire_time, "processing")
    job_id = __import__("uuid").uuid4().hex

    if db is not None:
        now = datetime.now(timezone.utc)
        db.subtitle_translation_jobs.insert_one(
            {
                "_id": job_id,
                "video_id": video_id,
                "user_id": user_id,
                "status": "processing",
                "requested_at": now,
                "source_language": source_language,
                "target_language": target_language,
            }
        )

    asyncio.create_task(
        _run_translation_job(
            video_id=video_id,
            target_language=target_language,
            source_language=source_language,
            expire_time=expire_time,
            job_id=job_id,
            user_id=user_id,
        )
    )

    return JSONResponse(
        status_code=202,
        content={
            "ok": True,
            "video_id": video_id,
            "target_language": target_language,
            "status": "processing",
        },
    )


@router.get("/api/subtitles/{video_id}/translation/status")
async def get_translation_status(video_id: str, target_language: str = TRANSLATION_DEFAULT_TARGET_LANGUAGE):
    redis_client = get_redis_client()
    target_language = (target_language or TRANSLATION_DEFAULT_TARGET_LANGUAGE or "ru").strip().lower()

    data_key, status_key, processing_key = _translation_keys(video_id, target_language)

    status = redis_client.get(status_key)
    if status:
        if isinstance(status, bytes):
            status = status.decode("utf-8", errors="replace")
        return {
            "ok": True,
            "video_id": video_id,
            "target_language": target_language,
            "status": status,
        }

    if redis_client.get(data_key):
        return {
            "ok": True,
            "video_id": video_id,
            "target_language": target_language,
            "status": "done",
        }

    db = _mongo_db()
    if db is not None:
        doc = db.subtitle_translations.find_one(
            {"video_id": video_id, "target_language": target_language},
            sort=[("generated_at", -1)],
        )
        if doc:
            return {
                "ok": True,
                "video_id": video_id,
                "target_language": target_language,
                "status": "done",
            }

    if redis_client.exists(processing_key):
        return {
            "ok": True,
            "video_id": video_id,
            "target_language": target_language,
            "status": "processing",
        }

    return {
        "ok": False,
        "video_id": video_id,
        "target_language": target_language,
        "status": "not_found",
    }


@router.get("/api/subtitles/{video_id}/translation")
async def get_translation(video_id: str, target_language: str = TRANSLATION_DEFAULT_TARGET_LANGUAGE) -> JSONResponse:
    redis_client = get_redis_client()
    target_language = (target_language or TRANSLATION_DEFAULT_TARGET_LANGUAGE or "ru").strip().lower()

    data_key, _, processing_key = _translation_keys(video_id, target_language)
    cached = redis_client.get(data_key)
    if cached:
        if isinstance(cached, bytes):
            cached = cached.decode("utf-8", errors="replace")
        return JSONResponse(
            status_code=200,
            content={
                "ok": True,
                "video_id": video_id,
                "target_language": target_language,
                "translation": json.loads(cached),
            },
        )

    db = _mongo_db()
    if db is not None:
        doc = db.subtitle_translations.find_one(
            {"video_id": video_id, "target_language": target_language},
            sort=[("generated_at", -1)],
        )
        if doc:
            payload = _build_translation_payload(doc)
            expire_time = int(os.getenv("DOWNLOADING_EXPIRE_TIME", 3600))
            redis_client.setex(data_key, expire_time * 2, json.dumps(payload, ensure_ascii=False))
            return JSONResponse(
                status_code=200,
                content={
                    "ok": True,
                    "video_id": video_id,
                    "target_language": target_language,
                    "translation": payload,
                },
            )

    if redis_client.exists(processing_key):
        return JSONResponse(
            status_code=202,
            content={
                "ok": True,
                "video_id": video_id,
                "target_language": target_language,
                "detail": "processing",
            },
        )

    raise HTTPException(status_code=404, detail="Translation not found")
