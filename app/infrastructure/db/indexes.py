import logging

from pymongo.errors import OperationFailure

from app.infrastructure.db.mongo_client import get_mongo_db

log = logging.getLogger("app.db.indexes")


async def _safe_create_index(collection, keys, **kwargs) -> None:
    """Create index if possible; ignore idempotent name/options conflicts."""
    try:
        await collection.create_index(keys, **kwargs)
    except OperationFailure as exc:
        # Common idempotent cases:
        # 85 IndexOptionsConflict, 86 IndexKeySpecsConflict
        if getattr(exc, "code", None) in (85, 86):
            log.warning("Skipping index creation due to existing equivalent/conflicting index: %s", exc)
            return
        raise


async def ensure_indexes() -> None:
    db = get_mongo_db()
    await _safe_create_index(
        db.app_updates,
        [("is_active", 1), ("starts_at", 1), ("ends_at", 1), ("created_at", -1)],
        name="app_updates_active_window",
    )
    await _safe_create_index(
        db.update_ack,
        [("update_id", 1), ("device_id", 1)],
        name="update_ack_update_device",
    )
    await _safe_create_index(
        db.update_ack,
        [("update_id", 1), ("user_id", 1)],
        name="update_ack_update_user",
    )
    await _safe_create_index(
        db.watch_progress,
        [("user_id", 1), ("video_id", 1)],
        name="watch_progress_user_video_unique",
        unique=True,
    )
    await _safe_create_index(
        db.watch_progress,
        [("user_id", 1), ("last_viewed_at", -1)],
    )
    await _safe_create_index(
        db.user_watched_videos,
        [("user_id", 1), ("video_id", 1)],
        name="user_watched_videos_user_video_unique",
        unique=True,
    )
    await _safe_create_index(
        db.user_watched_videos,
        [("user_id", 1), ("last_watched_at", -1)],
    )
