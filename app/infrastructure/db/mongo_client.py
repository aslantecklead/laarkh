import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from motor.motor_asyncio import AsyncIOMotorClient

from app.infrastructure.cache.session_store import get_session, touch_session as touch_session_store

_clients: Dict[int, AsyncIOMotorClient] = {}
_SHARED_USER_ID = "public"


def _loop_key() -> int:
    try:
        loop = asyncio.get_running_loop()
        return id(loop)
    except RuntimeError:
        return -1


def get_mongo_client() -> AsyncIOMotorClient:
    key = _loop_key()
    client = _clients.get(key)
    if client is None:
        uri = os.getenv("MONGO_URI", "mongodb://admin:admin@localhost:27017/linguada?authSource=admin")
        client = AsyncIOMotorClient(uri)
        _clients[key] = client
    return client


def get_mongo_db():
    db_name = os.getenv("MONGO_DB", "linguada")
    return get_mongo_client()[db_name]


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


def _parse_test_user_ids_env() -> Set[str]:
    raw = os.getenv("TEST_USER_IDS", "")
    if not raw:
        return set()
    return {v.strip() for v in raw.split(",") if v.strip()}


def _is_test_user_from_env(user_id: str) -> bool:
    if not user_id or user_id == _SHARED_USER_ID:
        return False
    return user_id in _parse_test_user_ids_env()


async def get_test_user_ids(*, include_public: bool = False) -> Set[str]:
    ids: Set[str] = set(_parse_test_user_ids_env())
    db = get_mongo_db()
    cursor = db.users.find({"flags.is_test": True}, {"_id": 1})
    docs = await cursor.to_list(length=None)
    for doc in docs:
        user_id = str(doc.get("_id") or "")
        if user_id:
            ids.add(user_id)
    if not include_public:
        ids.discard(_SHARED_USER_ID)
    return ids


async def ensure_user(
    user_id: str,
    device_id: Optional[str] = None,
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    if not user_id:
        raise ValueError("user_id is required")
    db = get_mongo_db()
    users = db.users
    now = datetime.now(timezone.utc)

    set_doc: Dict[str, Any] = {
        "updated_at": now,
        "last_login_at": now,
        "device_id": device_id,
    }
    if _is_test_user_from_env(user_id):
        set_doc["flags.is_test"] = True
    if meta:
        for field in (
            "session_id",
            "locale",
            "timezone",
            "app_version",
            "platform",
            "country",
            "ip",
        ):
            if field in meta:
                set_doc[field] = meta.get(field)
    set_doc = _drop_none(set_doc)

    insert_doc: Dict[str, Any] = {
        "_id": user_id,
        "username": "anonymous",
        "created_at": now,
    }

    await users.update_one(
        {"_id": user_id},
        {"$set": set_doc, "$setOnInsert": insert_doc},
        upsert=True,
    )
    await db.user_stats.update_one(
        {"_id": user_id},
        {"$set": {"last_active_at": now}, "$setOnInsert": {"_id": user_id}},
        upsert=True,
    )
    return user_id


class IdentityResolutionError(ValueError):
    pass


async def resolve_identity(
    *,
    user_id: Optional[str] = None,
    device_id: Optional[str] = None,
    session_id: Optional[str] = None,
    touch_session: bool = False,
) -> Dict[str, Optional[str]]:
    if session_id:
        session = await get_session(session_id)
        if not session:
            raise IdentityResolutionError("session not found")
        if touch_session:
            await touch_session_store(session_id, {"user_id": user_id} if user_id else {})
        resolved_device_id = device_id or session.get("device_id")
        resolved_user_id = user_id or session.get("user_id") or resolved_device_id
        return {"user_id": resolved_user_id, "device_id": resolved_device_id, "session_id": session_id}

    if user_id and device_id:
        return {"user_id": user_id, "device_id": device_id, "session_id": session_id}

    if user_id:
        return {"user_id": user_id, "device_id": device_id, "session_id": session_id}

    if device_id:
        return {"user_id": device_id, "device_id": device_id, "session_id": session_id}

    raise IdentityResolutionError("device_id or user_id or session_id is required")
