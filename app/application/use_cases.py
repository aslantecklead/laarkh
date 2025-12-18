from typing import Dict, Any
from fastapi import Depends

from app.infrastructure.worker import AudioDownloader
from app.core.exceptions import VideoTooLongError

class DownloadAudioUseCase:
    def __init__(self, downloader: AudioDownloader = Depends()):
        self.downloader = downloader

    async def execute(self, url: str) -> Dict[str, Any]:
        if not url:
            raise ValueError("URL is required")
            
        return await self.downloader.download_audio(url)