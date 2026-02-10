import logging
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.infrastructure.cache.session_store import (
    end_session as end_session_store,
    get_session,
    save_session,
    touch_session,
)
from app.infrastructure.db.mongo_client import ensure_user, get_mongo_db

router = APIRouter()
log = logging.getLogger("app.sessions")


def _mongo_db():
    try:
        return get_mongo_db()
    except Exception:
        log.exception("MongoDB unavailable")
        return None


def _drop_none(d: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in d.items() if v is not None}


@router.post("/api/session/start")
async def start_session(request_body: Dict[str, Any], fastapi_request: Request) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    device_id = request_body.get("device_id")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")

    user_id = request_body.get("user_id")
    now = datetime.now(timezone.utc)
    session_id = __import__("uuid").uuid4().hex

    await ensure_user(
        user_id=user_id or device_id,
        device_id=device_id,
        meta={
            "session_id": session_id,
            "locale": request_body.get("locale"),
            "timezone": request_body.get("timezone"),
            "app_version": request_body.get("app_version"),
            "platform": request_body.get("platform"),
            "country": request_body.get("country"),
            "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
        },
    )

    doc = {
        "session_id": session_id,
        "device_id": device_id,
        "user_id": user_id,
        "started_at": now.isoformat(),
        "last_seen_at": now.isoformat(),
        "ended_at": None,
        "app_version": request_body.get("app_version"),
        "platform": request_body.get("platform"),
        "country": request_body.get("country"),
        "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
        "locale": request_body.get("locale"),
        "timezone": request_body.get("timezone"),
    }
    doc = _drop_none(doc)
    await save_session(session_id, doc)

    return JSONResponse(
        status_code=200,
        content={"ok": True, "session_id": session_id, "user_id": user_id or device_id, "device_id": device_id},
    )


@router.post("/api/session/heartbeat")
async def heartbeat_session(request_body: Dict[str, Any], fastapi_request: Request) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    session_id = request_body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    session = await get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="session not found")

    device_id = request_body.get("device_id") or session.get("device_id")
    user_id = request_body.get("user_id") or session.get("user_id")
    now = datetime.now(timezone.utc)

    update_doc = {
        "last_seen_at": now.isoformat(),
        "device_id": device_id,
        "user_id": user_id,
        "app_version": request_body.get("app_version"),
        "platform": request_body.get("platform"),
        "country": request_body.get("country"),
        "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
        "locale": request_body.get("locale"),
        "timezone": request_body.get("timezone"),
    }
    update_doc = _drop_none(update_doc)

    await touch_session(session_id, update_doc)

    if device_id:
        await ensure_user(
            user_id=user_id or device_id,
            device_id=device_id,
            meta={
                "session_id": session_id,
                "locale": request_body.get("locale"),
                "timezone": request_body.get("timezone"),
                "app_version": request_body.get("app_version"),
                "platform": request_body.get("platform"),
                "country": request_body.get("country"),
                "ip": request_body.get("ip") or getattr(fastapi_request.client, "host", None),
            },
        )

    return JSONResponse(status_code=200, content={"ok": True})


@router.post("/api/session/end")
async def end_session(request_body: Dict[str, Any]) -> JSONResponse:
    db = _mongo_db()
    if db is None:
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    session_id = request_body.get("session_id")
    if not session_id:
        raise HTTPException(status_code=400, detail="session_id is required")

    ended = await end_session_store(session_id)
    if ended is None:
        raise HTTPException(status_code=404, detail="session not found")

    return JSONResponse(status_code=200, content={"ok": True})
