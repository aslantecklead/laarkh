import time
from pathlib import Path
from typing import Dict, Any, Union, Optional, List
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import numpy as np
import os
import subprocess
import tempfile
import logging

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

# ---------------------------
# Model cache with persistent storage
# ---------------------------
_MODEL_CACHE: Dict[tuple, WhisperModel] = {}
_MODEL_LOCK = threading.Lock()

# Создаем отдельную директорию для кэша моделей Linguada
LINGUADA_CACHE_DIR = Path.home() / ".cache" / "linguada" / "models"
LINGUADA_CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Устанавливаем переменные окружения для кэширования
os.environ["HF_HOME"] = str(LINGUADA_CACHE_DIR)
os.environ["TRANSFORMERS_CACHE"] = str(LINGUADA_CACHE_DIR)
os.environ["HF_DATASETS_CACHE"] = str(LINGUADA_CACHE_DIR)


# Проверяем существование модели в кэше
def _is_model_cached(model_size: str) -> bool:
    """Проверяет, есть ли модель в кэше"""
    model_dir = LINGUADA_CACHE_DIR / f"models--Systran--faster-whisper-{model_size}"
    return model_dir.exists() and any(model_dir.glob("**/*.bin"))


def _get_model(model_size: str, compute_type: str, num_workers: int = 4) -> WhisperModel:
    """Получение модели с кэшированием и настройкой воркеров"""
    key = (model_size, compute_type, num_workers)

    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            # CPU-специфичные оптимизации
            cpu_count = os.cpu_count() or 4
            threads = min(num_workers, cpu_count)

            # Проверяем кэш
            if not _is_model_cached(model_size):
                logger.info(f"Model {model_size} not found in cache, downloading...")
            else:
                logger.info(f"Loading model {model_size} from cache...")

            # Создаем модель с указанием директории для кэша
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=threads,  # Важно для CPU!
                num_workers=threads,  # Параллельная обработка
                download_root=str(LINGUADA_CACHE_DIR),  # Явно указываем директорию
            )
            _MODEL_CACHE[key] = model
            logger.info(
                f"✅ Loaded model {model_size} with {threads} CPU threads (cached: {_is_model_cached(model_size)})")
        return model


# Функция для предварительной загрузки моделей
def preload_models():
    """Предварительная загрузка моделей при старте приложения"""
    logger.info("Starting model preloading...")

    # Модели для предварительной загрузки
    models_to_preload = [
        ("tiny", "int8", 2),
        ("base", "int8", 2),
    ]

    for model_size, compute_type, workers in models_to_preload:
        try:
            _get_model(model_size, compute_type, workers)
            logger.info(f"✓ Preloaded model: {model_size}")
        except Exception as e:
            logger.warning(f"Failed to preload {model_size}: {e}")


# ---------------------------
# Ultra Fast Whisper ASR
# ---------------------------
class WhisperASR:
    """
    МАКСИМАЛЬНО БЫСТРЫЙ Whisper на CPU
    Оптимизировано для массовой транскрибации
    """

    def __init__(
            self,
            *,
            model_size: str = "tiny",  # 🚀 Самый быстрый
            compute_type: str = "int8",  # 🚀 Лучшая скорость на CPU
            language: Optional[str] = "en",  # 🚀 Фиксированный язык = +30% скорости
            vad_filter: bool = True,  # 🚀 Убирает тишину
            num_workers: int = 4,  # 🚀 Параллельная обработка (обновлено до 4)
            beam_size: int = 1,  # 🚀 Greedy декодирование
    ):
        self.model_size = model_size
        self.compute_type = compute_type
        self.language = language
        self.vad_filter = vad_filter
        self.num_workers = max(1, num_workers)
        self.beam_size = beam_size

        # Оптимальные параметры для скорости
        self.transcribe_kwargs = {
            "language": self.language,
            "beam_size": self.beam_size,
            "best_of": 1,  # 🚀 Минимизация поиска
            "temperature": 0.0,  # 🚀 Детерминированный вывод
            "compression_ratio_threshold": 1.8,  # 🚀 Меньше проверок
            "log_prob_threshold": -0.5,  # 🚀 Меньше фильтрации
            "no_speech_threshold": 0.4,  # 🚀 Меньше пропусков тишины
            "condition_on_previous_text": False,  # 🚀 Не зависит от контекста
            "initial_prompt": None,  # 🚀 Без промпта
            "word_timestamps": True,  # ✅ Требуется по заданию
            "prepend_punctuations": "\"'“¿([{-",  # Стандартное значение
            "append_punctuations": "\"'.。,，!！?？:：”)]}、",  # Стандартное значение
            "vad_filter": self.vad_filter,
            "vad_parameters": {
                "threshold": 0.3,  # 🚀 Более агрессивный VAD
                "min_speech_duration_ms": 250,
                "max_speech_duration_s": float('inf'),
                "min_silence_duration_ms": 200,
            }
        }

        # Загружаем модель через наш кэш
        self.model = _get_model(model_size, compute_type, self.num_workers)

    def transcribe(self, audio_path: Union[str, Path]) -> Dict[str, Any]:
        audio_path = Path(audio_path)
        if not audio_path.exists():
            raise FileNotFoundError(audio_path)

        t0 = time.perf_counter()

        # 🚀 Параллельная обработка длинных аудио
        if self._should_split_audio(audio_path):
            return self._transcribe_parallel(audio_path)

        # Стандартная обработка для коротких файлов
        segments_iter, info = self.model.transcribe(
            str(audio_path),
            **self.transcribe_kwargs
        )

        # 🚀 Параллельная обработка сегментов
        segments_out = self._process_segments_parallel(segments_iter)

        asr_time = time.perf_counter() - t0
        result = self._build_result(segments_out, info, asr_time, audio_path)

        return result

    def _should_split_audio(self, audio_path: Path, threshold_sec: int = 300) -> bool:
        """Определяем, нужно ли разбивать аудио на части для параллельной обработки"""
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(audio_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            duration = float(result.stdout.strip())
            return duration > threshold_sec and self.num_workers > 1
        except:
            return False

    def _transcribe_parallel(self, audio_path: Path) -> Dict[str, Any]:
        """Параллельная транскрибация длинных аудио"""
        t0 = time.perf_counter()

        # Разбиваем аудио на части
        audio_chunks = self._split_audio_into_chunks(audio_path)

        # Параллельная обработка чанков
        all_segments = []
        with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
            futures = []
            for chunk_path in audio_chunks:
                future = executor.submit(self._transcribe_chunk, chunk_path)
                futures.append(future)

            for future in as_completed(futures):
                segments, chunk_start = future.result()
                # Корректируем таймкоды
                for seg in segments:
                    seg["start"] += chunk_start
                    seg["end"] += chunk_start
                    if "words" in seg:
                        for word in seg["words"]:
                            word["start"] += chunk_start
                            word["end"] += chunk_start
                all_segments.extend(segments)

        # Сортируем по времени
        all_segments.sort(key=lambda x: x["start"])

        # Очищаем временные файлы
        for chunk in audio_chunks:
            chunk.unlink(missing_ok=True)

        asr_time = time.perf_counter() - t0
        result = self._build_result(all_segments, None, asr_time, audio_path)

        return result

    def _split_audio_into_chunks(self, audio_path: Path, chunk_duration: int = 180) -> List[Path]:
        """Разбиваем аудио на чанки по N секунд"""
        chunks = []
        temp_dir = tempfile.mkdtemp(prefix="whisper_chunks_")

        # Определяем длину аудио
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(audio_path)
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        total_duration = float(result.stdout.strip())

        # Создаем чанки
        for i, start in enumerate(np.arange(0, total_duration, chunk_duration)):
            chunk_path = Path(temp_dir) / f"chunk_{i:03d}.wav"

            cmd = [
                "ffmpeg", "-i", str(audio_path),
                "-ss", str(start),
                "-t", str(chunk_duration),
                "-ar", "16000",
                "-ac", "1",
                "-acodec", "pcm_s16le",
                "-y", str(chunk_path)
            ]

            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)

            if chunk_path.exists() and chunk_path.stat().st_size > 0:
                chunks.append(chunk_path)

        # Если чанки не создались, возвращаем оригинальный файл как единственный чанк
        if not chunks:
            return [audio_path]

        return chunks

    def _transcribe_chunk(self, chunk_path: Path):
        """Транскрибация одного чанка"""
        # Получаем время начала чанка из имени файла
        chunk_start = 0
        if "_" in chunk_path.stem:
            try:
                # Извлекаем номер из имени типа "chunk_000"
                parts = chunk_path.stem.split("_")
                if len(parts) > 1 and parts[-1].isdigit():
                    chunk_num = int(parts[-1])
                    chunk_start = chunk_num * 180  # 3 минуты на чанк
            except:
                pass

        segments_iter, _ = self.model.transcribe(
            str(chunk_path),
            **self.transcribe_kwargs
        )

        segments = []
        for i, seg in enumerate(segments_iter):
            segment_data = self._process_segment(i, seg)
            segments.append(segment_data)

        return segments, chunk_start

    def _process_segments_parallel(self, segments_iter):
        """Параллельная обработка сегментов"""
        segments = []

        # Собираем все сегменты сначала
        segment_list = list(enumerate(segments_iter))

        if not segment_list:
            return segments

        # Обрабатываем в пуле потоков
        with ThreadPoolExecutor(max_workers=min(4, self.num_workers)) as executor:
            futures = [executor.submit(self._process_segment, i, seg)
                       for i, seg in segment_list]

            for future in as_completed(futures):
                segments.append(future.result())

        # Сортируем по ID
        segments.sort(key=lambda x: x["id"])
        return segments

    def _process_segment(self, idx: int, seg) -> Dict[str, Any]:
        """Обработка одного сегмента"""
        text = (seg.text or "").strip()

        segment_data = {
            "id": idx,
            "start": float(seg.start),
            "end": float(seg.end),
            "text": text,
            "words": [],
        }

        if hasattr(seg, 'words') and seg.words:
            segment_data["words"] = [
                {
                    "word": (w.word or "").strip(),
                    "start": float(w.start),
                    "end": float(w.end),
                    "confidence": float(w.probability) if w.probability is not None else 0.9,
                }
                for w in seg.words
            ]

        return segment_data

    def _build_result(self, segments_out, info, asr_time: float, audio_path: Path) -> Dict[str, Any]:
        """Сборка финального результата"""
        # Получаем длительность аудио
        duration = None
        if segments_out:
            duration = segments_out[-1]["end"]
        else:
            try:
                cmd = [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(audio_path)
                ]
                result = subprocess.run(cmd, capture_output=True, text=True)
                duration = float(result.stdout.strip())
            except:
                duration = None

        # Собираем полный текст
        full_text = " ".join([seg["text"] for seg in segments_out if seg["text"].strip()])

        rtf = asr_time / duration if duration and duration > 0 else None

        # Добавляем информацию о кэше
        cache_info = {
            "cached": _is_model_cached(self.model_size),
            "cache_dir": str(LINGUADA_CACHE_DIR),
            "cache_size_mb": self._get_cache_size_mb(),
        }

        return {
            "text": full_text,
            "language": getattr(info, "language", self.language) if info else self.language,
            "segments": segments_out,
            "meta": {
                "engine": "ultra-fast-whisper",
                "model": self.model_size,
                "compute_type": self.compute_type,
                "device": "cpu",
                "num_workers": self.num_workers,
                "beam_size": self.beam_size,
                "language_hint": self.language,
                "vad_filter": self.vad_filter,
                "duration_audio_sec": duration,
                "asr_time_sec": round(asr_time, 2),
                "rtf": round(rtf, 3) if rtf else None,
                "speedup_factor": round((duration or 0) / asr_time, 1) if asr_time > 0 else None,
                "cache": cache_info,
            },
        }

    def _get_cache_size_mb(self) -> float:
        """Получаем размер кэша в MB"""
        try:
            total_size = 0
            for path in LINGUADA_CACHE_DIR.rglob("*"):
                if path.is_file():
                    total_size += path.stat().st_size
            return round(total_size / (1024 * 1024), 2)
        except:
            return 0.0


# Функция для очистки кэша
def clear_model_cache():
    """Очищает кэш моделей"""
    try:
        import shutil
        if LINGUADA_CACHE_DIR.exists():
            shutil.rmtree(LINGUADA_CACHE_DIR)
            logger.info(f"Cache cleared: {LINGUADA_CACHE_DIR}")
        # Создаем заново пустую директорию
        LINGUADA_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return True
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        return False


# Экспортируем функцию предзагрузки
__all__ = ['WhisperASR', 'preload_models', 'clear_model_cache']