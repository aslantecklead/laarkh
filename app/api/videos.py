import logging

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.infrastructure.video_catalog import get_video_catalog_use_case

router = APIRouter()
log = logging.getLogger("app.videos")


@router.get("/api/videos")
async def list_available_videos() -> JSONResponse:
    use_case = get_video_catalog_use_case()
    try:
        videos, source = use_case.execute()
    except Exception:
        log.exception("Failed to load videos from Berios")
        raise HTTPException(status_code=503, detail="MongoDB unavailable")

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "source": source,
            "videos": videos,
        },
    )
