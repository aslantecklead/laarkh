from app.infrastructure.db.mongo_client import get_mongo_db


async def ensure_indexes() -> None:
    db = get_mongo_db()
    await db.app_updates.create_index(
        [("is_active", 1), ("starts_at", 1), ("ends_at", 1), ("created_at", -1)],
        name="app_updates_active_window",
    )
    await db.update_ack.create_index(
        [("update_id", 1), ("device_id", 1)],
        name="update_ack_update_device",
    )
    await db.update_ack.create_index(
        [("update_id", 1), ("user_id", 1)],
        name="update_ack_update_user",
    )
