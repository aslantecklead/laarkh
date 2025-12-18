from fastapi import APIRouter, HTTPException, Depends, Request
from typing import Dict, Any
import os

from app.application.use_cases import DownloadAudioUseCase
from app.infrastructure.cache.rate_limit import rate_limit
from app.infrastructure.cache.redis_client import get_redis_client

router = APIRouter()

@router.post("/api/download")
@rate_limit(by_ip=True)
async def download_audio(request: Dict[str, Any], fastapi_request: Request, use_case: DownloadAudioUseCase = Depends()) -> Dict[str, Any]:
    try:
        video_id = request.get("video_id")
        url = request.get("url")
        
        if not video_id or not url:
            raise HTTPException(status_code=400, detail="video_id and url are required")
            
        # Получаем время хранения из переменных окружения
        expire_time = int(os.getenv('DOWNLOADING_EXPIRE_TIME', 300))
        
        # Check if video is already being processed
        redis_client = get_redis_client()
        status_key = f"status:{video_id}"
        downloading_key = f"{video_id}:downloading"
        
        # Set downloading flag with NX (only if not exists) and EX (expire in 300 seconds)
        is_downloading = redis_client.set(downloading_key, "1", ex=expire_time, nx=True)
        if not is_downloading:
            raise HTTPException(status_code=429, detail="Video is already being processed")
            
        try:
            # Update status
            redis_client.setex(status_key, expire_time, "downloading")
            
            result = await use_case.execute(url)
            
            return {"ok": True, "video_id": result["id"], "audio": result}
            
        except Exception as e:
            # Clean up on error
            redis_client.delete(downloading_key)
            redis_client.delete(status_key)
            raise
            
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    finally:
        # Clean up downloading flag
        redis_client = get_redis_client()
        downloading_key = f"{request.get('video_id')}:downloading"
        redis_client.delete(downloading_key)