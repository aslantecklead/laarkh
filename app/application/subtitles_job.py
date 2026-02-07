import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict

from app.application.use_cases import GenerateSubtitlesUseCase
from app.infrastructure.cache.redis_client import get_redis_client
from app.infrastructure.db.mongo_client import get_mongo_db

log = logging.getLogger("app.subtitles_job")


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


async def run_subtitles_job(url: str, video_id: str, expire_time: int, job_id: str, user_id: str) -> None:
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

        db = get_mongo_db()
        if db is not None:
            now = datetime.now(timezone.utc)
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
            subtitle_insert = await db.subtitles.insert_one(subtitle_doc)

            await db.subtitle_jobs.update_one(
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

        await redis_client.setex(subtitles_key, expire_time * 2, json.dumps(subtitles))
        await redis_client.setex(status_key, expire_time, "done")

        log.info("[JOB] done video_id=%s", video_id)

    except Exception as e:
        log.exception("[JOB] error video_id=%s: %s", video_id, e)
        db = get_mongo_db()
        if db is not None:
            await db.subtitle_jobs.update_one(
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
            await redis_client.setex(status_key, expire_time, "error")
        except Exception:
            pass
    finally:
        try:
            await redis_client.delete(processing_key)
        except Exception:
            pass
