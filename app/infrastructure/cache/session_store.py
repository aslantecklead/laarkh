import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.infrastructure.cache.redis_client import get_redis_client


SESSION_KEY_PREFIX = "session:"
DEFAULT_SESSION_TTL_SEC = int(os.getenv("SESSION_TTL_SEC", "604800"))


def _key(session_id: str) -> str:
    return f"{SESSION_KEY_PREFIX}{session_id}"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def get_session(session_id: str) -> Optional[Dict[str, Any]]:
    redis = get_redis_client()
    raw = await redis.get(_key(session_id))
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        return json.loads(raw)
    except Exception:
        return None


async def save_session(session_id: str, data: Dict[str, Any], ttl_sec: Optional[int] = None) -> None:
    redis = get_redis_client()
    ttl = ttl_sec or DEFAULT_SESSION_TTL_SEC
    payload = json.dumps(data, ensure_ascii=False)
    await redis.setex(_key(session_id), ttl, payload)


async def touch_session(
    session_id: str,
    updates: Dict[str, Any],
    ttl_sec: Optional[int] = None,
    preserve_ttl: bool = True,
) -> Optional[Dict[str, Any]]:
    redis = get_redis_client()
    session = await get_session(session_id)
    if session is None:
        return None
    session.update(updates)
    if "last_seen_at" not in updates:
        session["last_seen_at"] = _now_iso()

    ttl = ttl_sec or DEFAULT_SESSION_TTL_SEC
    if preserve_ttl:
        current_ttl = await redis.ttl(_key(session_id))
        if current_ttl and current_ttl > 0:
            ttl = int(current_ttl)

    payload = json.dumps(session, ensure_ascii=False)
    await redis.setex(_key(session_id), ttl, payload)
    return session


async def end_session(session_id: str, ttl_sec: Optional[int] = None) -> Optional[Dict[str, Any]]:
    return await touch_session(
        session_id,
        {"ended_at": _now_iso(), "last_seen_at": _now_iso()},
        ttl_sec=ttl_sec,
        preserve_ttl=True,
    )
