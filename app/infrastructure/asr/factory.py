# app/infrastructure/asr/factory.py
"""
ASR engine factory with caching.
"""

import os
from pathlib import Path
from app.infrastructure.asr.whisper_asr import WhisperASR, preload_models

# Создаем директорию для кэша при импорте
cache_dir = Path.home() / ".cache" / "linguada" / "models"
cache_dir.mkdir(parents=True, exist_ok=True)

# Устанавливаем переменные окружения для кэширования
os.environ["HF_HOME"] = str(cache_dir)
os.environ["TRANSFORMERS_CACHE"] = str(cache_dir)
os.environ["HF_DATASETS_CACHE"] = str(cache_dir)


def get_asr_engine():
    """
    Returns an instance of the ASR engine with optimal settings for speed.
    Uses local cache to avoid downloading models every time.

    Returns:
        WhisperASR: Configured ASR engine instance
    """
    return WhisperASR(
        model_size="tiny",  # Fastest model (78 MB)
        compute_type="int8",  # Optimal for CPU
        language="en",  # Fixed language for speed
        vad_filter=True,  # Remove silence (speeds up processing)
        num_workers=4,  # Use all CPU cores for parallel processing
        beam_size=1,  # Greedy decoding for maximum speed
    )


# Функция для предварительной загрузки моделей при старте
def initialize_asr():
    """Initialize ASR system with model preloading"""
    preload_models()