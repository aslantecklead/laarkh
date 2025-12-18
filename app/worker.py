from urllib.parse import urlparse, parse_qs
from pathlib import Path
import json
import subprocess

import yt_dlp
from fastapi import HTTPException

from app.config import DOWNLOAD_DIR, AUDIO_CHANNELS, AUDIO_SAMPLE_RATE, AUDIO_BITRATE, MAX_AUDIO_DURATION


def extract_video_id(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc in ("youtu.be", "www.youtu.be"):
        vid = parsed.path.lstrip("/")
        return vid or None
    qs = parse_qs(parsed.query)
    if "v" in qs and qs["v"]:
        return qs["v"][0]
    return None


def ffprobe_audio(path: Path) -> dict | None:
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=codec_name,sample_rate,channels,bit_rate,duration",
            "-of", "json",
            str(path),
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        data = json.loads(out)
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        br = s.get("bit_rate")
        return {
            "codec": s.get("codec_name"),
            "sample_rate": int(s["sample_rate"]) if s.get("sample_rate") else None,
            "channels": int(s["channels"]) if s.get("channels") else None,
            "bit_rate": int(br) if br and br.isdigit() else None,
            "duration": float(s["duration"]) if s.get("duration") else None,
        }
    except Exception:
        return None


def _find_latest_opus(video_id: str) -> Path | None:
    candidates = list(DOWNLOAD_DIR.glob(f"{video_id}.opus"))
    if not candidates:
        return None
    return candidates[0]


def _cleanup_non_opus(video_id: str, keep: Path | None):
    for p in DOWNLOAD_DIR.glob(f"{video_id}_*"):
        if keep and p.resolve() == keep.resolve():
            continue
        if p.suffix == ".opus" and p.name != f"{video_id}.opus":
            try:
                p.unlink()
            except Exception:
                pass
    for p in DOWNLOAD_DIR.glob(f"{video_id}_*"):
        if p.suffix != ".opus":
            try:
                p.unlink()
            except Exception:
                pass


def download_audio(url: str, video_id: str) -> dict:
    outtmpl = str(DOWNLOAD_DIR / "%(id)s.%(ext)s")

    ydl_opts = {
        "max_duration": MAX_AUDIO_DURATION,
        "format": "bestaudio[ext=webm]/bestaudio/best",
        "outtmpl": outtmpl,
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
            raise HTTPException(
                status_code=400,
                detail=f"Video duration {duration} seconds exceeds maximum allowed {MAX_AUDIO_DURATION} seconds"
            )
            
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        opus_path = _find_latest_opus(video_id)
        if not opus_path or not opus_path.exists():
            raise RuntimeError(
                "Opus output not found. "
                "Проверь, что установлен ffmpeg и что postprocessor отработал."
            )

        _cleanup_non_opus(video_id, keep=opus_path)
        actual = ffprobe_audio(opus_path)

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
            "actual": actual,
            "filesize_bytes": opus_path.stat().st_size,
        }

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Download error: {e}")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Unexpected error: {e}")
