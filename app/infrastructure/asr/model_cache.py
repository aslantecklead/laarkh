import os
import threading
from pathlib import Path
from faster_whisper import WhisperModel
import logging

logger = logging.getLogger(__name__)

# Глобальный кэш моделей
_MODEL_CACHE = {}
_MODEL_LOCK = threading.Lock()

# Директория для кэша
CACHE_DIR = Path.home() / ".cache" / "linguada" / "models"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Устанавливаем переменные окружения для кэширования
os.environ["HF_HOME"] = str(CACHE_DIR)
os.environ["TRANSFORMERS_CACHE"] = str(CACHE_DIR)
os.environ["HF_DATASETS_CACHE"] = str(CACHE_DIR)


def preload_models():
    """Предварительная загрузка моделей при старте приложения"""
    logger.info("Preloading Whisper models...")

    models_to_preload = [
        ("tiny", "int8"),
        ("base", "int8"),
        ("small", "int8"),
    ]

    for model_size, compute_type in models_to_preload:
        try:
            _get_or_load_model(model_size, compute_type, num_workers=2)
            logger.info(f"✓ Preloaded model: {model_size} ({compute_type})")
        except Exception as e:
            logger.warning(f"Failed to preload {model_size}: {e}")


def _get_or_load_model(model_size: str, compute_type: str, num_workers: int = 2):
    """Получение или загрузка модели с кэшированием"""
    key = (model_size, compute_type, num_workers)

    with _MODEL_LOCK:
        model = _MODEL_CACHE.get(key)
        if model is None:
            # CPU-специфичные оптимизации
            cpu_count = os.cpu_count() or 4
            threads = min(num_workers, cpu_count)

            logger.info(f"Loading model {model_size} ({compute_type})...")
            model = WhisperModel(
                model_size,
                device="cpu",
                compute_type=compute_type,
                cpu_threads=threads,
                num_workers=threads,
                download_root=str(CACHE_DIR),  # Явно указываем директорию для кэша
            )
            _MODEL_CACHE[key] = model
            logger.info(f"✅ Model {model_size} loaded with {threads} CPU threads")

        return model


# Экспортируем функцию для получения моделей
get_cached_model = _get_or_load_model