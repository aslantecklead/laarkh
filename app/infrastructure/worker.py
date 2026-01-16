import logging
import time
import uuid
from pathlib import Path
from typing import Any, Dict
import tempfile
import os
import subprocess
import threading

import yt_dlp

from app.config import MAX_AUDIO_DURATION
from app.core.exceptions import VideoTooLongError

logger = logging.getLogger("linguada.worker")

# Глобальная блокировка для yt-dlp
_YTDLP_LOCK = threading.Lock()


def _setup_logging_if_needed() -> None:
    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )


def _fmt_req(req_id: str) -> str:
    return f"[REQ {req_id}]"


class SubtitleGenerator:
    def __init__(self):
        _setup_logging_if_needed()
        # Ленивая загрузка ASR движка
        self._asr_engine = None
        self._asr_lock = threading.Lock()

    async def generate_subtitles(self, url: str, video_id: str) -> Dict[str, Any]:
        req_id = str(uuid.uuid4())[:8]
        t0 = time.time()
        logger.info(f"{_fmt_req(req_id)} start generate_subtitles video_id={video_id} url={url}")

        # 1. Извлечение информации о видео
        info = self._extract_info(req_id, url)

        # 2. Проверка длительности
        duration = info.get("duration")
        if duration and duration > MAX_AUDIO_DURATION:
            logger.warning(f"{_fmt_req(req_id)} video too long: {duration}s > {MAX_AUDIO_DURATION}s")
            raise VideoTooLongError(duration, MAX_AUDIO_DURATION)

        audio_path = None
        try:
            # 3. Скачивание аудио
            audio_path = self._download_audio(req_id, url, video_id)
            logger.info(f"{_fmt_req(req_id)} audio ready path={audio_path} size={audio_path.stat().st_size} bytes")

            # 4. Оптимизация аудио для Whisper
            optimized_audio = self._optimize_audio_for_whisper(audio_path)

            # 5. Получение ASR движка
            asr_engine = self._get_asr_engine()

            # 6. Транскрипция
            logger.info(f"{_fmt_req(req_id)} starting transcription...")
            t_asr = time.time()
            transcription = asr_engine.transcribe(optimized_audio)

            asr_time = time.time() - t_asr
            logger.info(f"{_fmt_req(req_id)} transcription done in {asr_time:.2f}s "
                        f"(RTF: {asr_time / duration if duration else 'N/A':.2f})")

            total = time.time() - t0
            logger.info(f"{_fmt_req(req_id)} done total={total:.2f}s")

            return {
                "video_id": video_id,
                "title": info.get("title"),
                "uploader": info.get("uploader"),
                "duration": duration,
                "subtitles": transcription,
            }

        finally:
            # 7. Очистка временных файлов
            self._cleanup_temp_files([audio_path, getattr(self, 'optimized_audio_path', None)])

    def _extract_info(self, req_id: str, url: str) -> Dict[str, Any]:
        """Извлечение информации о видео"""
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "socket_timeout": 10,
        }

        logger.info(f"{_fmt_req(req_id)} extracting info...")
        t = time.time()

        with _YTDLP_LOCK:
            with yt_dlp.YoutubeDL({**ydl_opts, "skip_download": True}) as ydl:
                info = ydl.extract_info(url, download=False)

        logger.info(f"{_fmt_req(req_id)} extracted info in {time.time() - t:.2f}s "
                    f"title={info.get('title', '')[:50]}...")
        return info

    def _download_audio(self, req_id: str, url: str, video_id: str) -> Path:
        """Скачивание аудио"""
        tmp_dir = Path(tempfile.mkdtemp(prefix=f"linguada_{video_id}_"))
        outtmpl = str(tmp_dir / "%(id)s.%(ext)s")

        ydl_opts = {
            "format": "bestaudio[ext=webm]/bestaudio/best",
            "outtmpl": outtmpl,
            "quiet": True,
            "no_warnings": True,
            "no_warnings": True,
            "noplaylist": True,
            "retries": 5,
            "socket_timeout": 20,
            "concurrent_fragment_downloads": 4,  # Умеренный параллелизм
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "opus",
            }],
        }

        logger.info(f"{_fmt_req(req_id)} downloading audio via yt-dlp to {tmp_dir} ...")
        t = time.time()

        with _YTDLP_LOCK:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

        download_time = time.time() - t
        logger.info(f"{_fmt_req(req_id)} yt-dlp download done in {download_time:.2f}s id={info.get('id')}")

        # Ищем скачанный файл
        opus_file = next(tmp_dir.glob(f"{info.get('id')}*.opus"), None)
        if not opus_file or not opus_file.exists():
            # Пробуем найти любой аудио файл
            for ext in ['opus', 'webm', 'm4a', 'mp3']:
                audio_file = next(tmp_dir.glob(f"*.{ext}"), None)
                if audio_file and audio_file.exists():
                    opus_file = audio_file
                    break

        if not opus_file or not opus_file.exists():
            files = [p.name for p in tmp_dir.iterdir()]
            raise RuntimeError(f"Audio output not found in {tmp_dir}. Files: {files}")

        # Перемещаем файл в отдельный временный файл
        temp_file = Path(tempfile.mktemp(suffix=opus_file.suffix))
        opus_file.rename(temp_file)

        # Удаляем временную директорию
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

        return temp_file

    def _optimize_audio_for_whisper(self, audio_path: Path) -> Path:
        """Конвертирует аудио в оптимальный для Whisper формат"""
        # Если уже WAV, проверяем параметры
        if audio_path.suffix.lower() == '.wav':
            # Проверяем параметры аудио
            try:
                cmd = [
                    "ffprobe", "-v", "error",
                    "-select_streams", "a:0",
                    "-show_entries", "stream=sample_rate,channels",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                params = result.stdout.strip().split('\n')
                if len(params) >= 2:
                    sample_rate = int(params[0])
                    channels = int(params[1])
                    if sample_rate == 16000 and channels == 1:
                        return audio_path
            except:
                pass

        # Конвертируем в оптимальный формат
        output_path = Path(tempfile.mktemp(suffix=".wav"))
        self.optimized_audio_path = output_path

        cmd = [
            "ffmpeg", "-i", str(audio_path),
            "-ar", "16000",  # Sample rate 16kHz
            "-ac", "1",  # Mono
            "-acodec", "pcm_s16le",  # 16-bit PCM
            "-y", str(output_path)
        ]

        try:
            subprocess.run(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True
            )
            return output_path
        except subprocess.CalledProcessError as e:
            logger.warning(f"FFmpeg optimization failed: {e}, using original audio")
            return audio_path

    def _get_asr_engine(self):
        """Ленивая загрузка ASR движка с кэшированием"""
        with self._asr_lock:
            if self._asr_engine is None:
                from app.infrastructure.asr.factory import get_asr_engine
                self._asr_engine = get_asr_engine()
        return self._asr_engine

    def _cleanup_temp_files(self, paths):
        """Очистка временных файлов"""
        for path in paths:
            if path and isinstance(path, Path) and path.exists():
                try:
                    path.unlink(missing_ok=True)
                except Exception as e:
                    logger.warning(f"Cleanup failed for {path}: {e}")