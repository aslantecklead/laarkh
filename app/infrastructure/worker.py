import yt_dlp
from pathlib import Path
from typing import Dict, Any
import requests
import tempfile
import os

from app.config import AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, AUDIO_BITRATE, MAX_AUDIO_DURATION
from app.core.exceptions import VideoTooLongError


class SubtitleGenerator:
    def __init__(self):
        pass

    async def generate_subtitles(self, url: str, video_id: str) -> Dict[str, Any]:        
        ydl_opts = {
            "max_duration": MAX_AUDIO_DURATION,
            "format": "bestaudio[ext=webm]/bestaudio/best",
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "concurrent_fragment_downloads": 10,
        }

        try:
            with yt_dlp.YoutubeDL({**ydl_opts, 'skip_download': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
            duration = info.get('duration')
            if duration and duration > MAX_AUDIO_DURATION:
                raise VideoTooLongError(duration, MAX_AUDIO_DURATION)
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                result = ydl.extract_info(url, download=False)
                audio_stream = next(s for s in result['formats'] if s.get('format_id') == '251')
                
                from app.infrastructure.asr.factory import get_asr_engine
                asr_engine = get_asr_engine()
                
                response = requests.get(audio_stream['url'], stream=True)
                response.raise_for_status()
                
                with tempfile.NamedTemporaryFile(suffix='.webm', delete=False) as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                    temp_path = f.name
                
                try:
                    transcription = asr_engine.transcribe(temp_path)
                finally:
                    os.unlink(temp_path)

            return {
                "video_id": video_id,
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "duration": info.get("duration"),
                "subtitles": transcription
            }

        except yt_dlp.utils.DownloadError as e:
            raise Exception(f"Download error: {e}")
        except Exception as e:
            raise Exception(f"Unexpected error: {e}")