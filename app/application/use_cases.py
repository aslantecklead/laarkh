from typing import Dict, Any
from fastapi import Depends

from app.infrastructure.worker import SubtitleGenerator
from app.core.exceptions import VideoTooLongError

class GenerateSubtitlesUseCase:
    def __init__(self, subtitle_generator: SubtitleGenerator = Depends()):
        self.subtitle_generator = subtitle_generator

    async def execute(self, url: str, video_id: str) -> Dict[str, Any]:
        if not url or not video_id:
            raise ValueError("URL and video_id are required")
            
        return await self.subtitle_generator.generate_subtitles(url, video_id)