import yt_dlp
from pathlib import Path
from typing import Dict, Any

from app.config import DOWNLOAD_DIR, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, AUDIO_BITRATE, MAX_AUDIO_DURATION
from app.core.exceptions import VideoTooLongError


class AudioDownloader:
    def __init__(self):
        self.download_dir = DOWNLOAD_DIR
        self.download_dir.mkdir(parents=True, exist_ok=True)

    async def download_audio(self, url: str) -> Dict[str, Any]:        
        ydl_opts = {
            "max_duration": MAX_AUDIO_DURATION,
            "format": "bestaudio[ext=webm]/bestaudio/best",
            "outtmpl": str(self.download_dir / "%(id)s.%(ext)s"),
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "concurrent_fragment_downloads": 10,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "opus",
            }],
            "postprocessor_args": [
                "-vn",
                "-ac", str(AUDIO_CHANNELS),
                "-ar", str(AUDIO_SAMPLE_RATE),
                "-b:a", "8k",
                "-application", "lowdelay",
                "-vbr", "on",
                "-compression_level", "10",
            ],
        }

        try:
            with yt_dlp.YoutubeDL({**ydl_opts, 'skip_download': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                
            duration = info.get('duration')
            if duration and duration > MAX_AUDIO_DURATION:
                raise VideoTooLongError(duration, MAX_AUDIO_DURATION)
                
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

            video_id = info.get("id")
            opus_path = self.download_dir / f"{video_id}.opus"
            
            if not opus_path.exists():
                raise RuntimeError("Opus output not found. Проверь, что установлен ffmpeg и что postprocessor отработал.")

            return {
                "id": info.get("id"),
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "duration": info.get("duration"),
                "filepath": str(opus_path),
                "filename": opus_path.name,
                "target": {
                    "codec": "opus",
                    "channels": AUDIO_CHANNELS,
                    "sample_rate": AUDIO_SAMPLE_RATE,
                    "bitrate": "8k",
                    "application": "lowdelay",
                },
            }

        except yt_dlp.utils.DownloadError as e:
            raise Exception(f"Download error: {e}")
        except Exception as e:
            raise Exception(f"Unexpected error: {e}")