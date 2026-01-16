from typing import Dict, Any
from fastapi import Depends

from app.infrastructure.worker import SubtitleGenerator  # <-- ВАЖНО: как у тебя сейчас
from app.core.exceptions import VideoTooLongError


def get_subtitle_generator() -> SubtitleGenerator:
    # Если захочешь singleton — можно хранить в глобальной переменной,
    # но пока оставляем как есть, чтобы "не ломать код".
    return SubtitleGenerator()


class GenerateSubtitlesUseCase:
    def __init__(self):
        self.subtitle_generator = SubtitleGenerator()

    async def execute(self, url: str, video_id: str) -> Dict[str, Any]:
        """Генерирует субтитры для видео по URL."""
        try:
            return await self.subtitle_generator.generate_subtitles(url, video_id)
        except VideoTooLongError as e:
            raise e
        except Exception as e:
            # Логируем ошибку и пробрасываем дальше
            import logging
            logger = logging.getLogger(__name__)
            logger.error(f"Error generating subtitles for {video_id}: {e}")
            raise


def get_generate_subtitles_use_case(
    subtitle_generator: SubtitleGenerator = Depends(get_subtitle_generator),
) -> GenerateSubtitlesUseCase:
    # Provider: FastAPI DI будет вызывать его.
    return GenerateSubtitlesUseCase(subtitle_generator=subtitle_generator)
