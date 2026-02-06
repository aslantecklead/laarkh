import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent  # .../app

def getenv_int(name: str, default: int) -> int:
    val = os.getenv(name)
    try:
        return int(val) if val is not None else default
    except ValueError:
        return default

def getenv_str(name: str, default: str | None = None) -> str | None:
    return os.getenv(name, default)

def getenv_bool(name: str, default: bool) -> bool:
    val = os.getenv(name)
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on")


# --- Audio ---
AUDIO_SAMPLE_RATE = getenv_int("AUDIO_SAMPLE_RATE", 16000)
AUDIO_BITRATE = getenv_str("AUDIO_BITRATE", "8k")
AUDIO_CHANNELS = getenv_int("AUDIO_CHANNELS", 1)

# --- Limits ---
MAX_CONCURRENT_DOWNLOADS = getenv_int("MAX_CONCURRENT_DOWNLOADS", 2)
MAX_AUDIO_DURATION = getenv_int("MAX_AUDIO_DURATION", 1800)  # 30 мин

# --- Infra ---
DATABASE_URL = getenv_str("DATABASE_URL")
REDIS_HOST = getenv_str("REDIS_HOST", "redis")
REDIS_PORT = getenv_int("REDIS_PORT", 6379)
REDIS_DB = getenv_int("REDIS_DB", 0)


# --- Video catalog ---
VIDEO_CATALOG_COLLECTION = getenv_str("VIDEO_CATALOG_COLLECTION", "videos")
VIDEO_CATALOG_CACHE_KEY = getenv_str("VIDEO_CATALOG_CACHE_KEY", "videos:all")
VIDEO_CATALOG_CACHE_TTL_SEC = getenv_int("VIDEO_CATALOG_CACHE_TTL_SEC", 600)

# --- ASR ---
ASR_MODEL_SIZE = getenv_str("ASR_MODEL_SIZE", "base")

# --- Translation ---
TRANSLATION_DEFAULT_SOURCE_LANGUAGE = getenv_str("TRANSLATION_SOURCE_LANGUAGE", "en")
TRANSLATION_DEFAULT_TARGET_LANGUAGE = getenv_str("TRANSLATION_TARGET_LANGUAGE", "ru")
TRANSLATION_AUTO_DOWNLOAD = getenv_bool("TRANSLATION_AUTO_DOWNLOAD", True)
