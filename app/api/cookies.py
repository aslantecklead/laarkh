import os
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _cookies_path() -> Path:
    raw_path = os.getenv("YTDLP_COOKIES", "cookies/youtube.txt")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path

def _cookie_header_path() -> Path:
    raw_path = os.getenv("YTDLP_COOKIE_HEADER_PATH", "cookies/cookie_header.txt")
    path = Path(raw_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path

def _looks_like_netscape(text: str) -> bool:
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        return line.startswith("# Netscape HTTP Cookie File")
    return False


@router.post("/api/cookies")
async def upload_cookies(request: Request) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    cookie_format = "netscape"
    if content_type.startswith("application/json"):
        payload: Dict[str, Any] = await request.json()
        cookies_text = payload.get("cookies")
        cookie_format = (payload.get("format") or "netscape").lower()
    else:
        body = await request.body()
        cookies_text = body.decode("utf-8", errors="replace")

    if not cookies_text or not cookies_text.strip():
        raise HTTPException(status_code=400, detail="cookies payload is empty")

    if cookie_format not in ("netscape", "header"):
        raise HTTPException(status_code=400, detail="format must be 'netscape' or 'header'")

    if cookie_format == "netscape":
        if not _looks_like_netscape(cookies_text):
            raise HTTPException(
                status_code=400,
                detail="cookies must be in Netscape format (export using cookies.txt browser extension)",
            )
        path = _cookies_path()
    else:
        path = _cookie_header_path()

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(cookies_text, encoding="utf-8")

    return JSONResponse(
        status_code=200,
        content={
            "ok": True,
            "path": str(path),
            "size": len(cookies_text),
            "format": cookie_format,
        },
    )
