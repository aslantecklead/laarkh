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

# --- ASR ---
ASR_MODEL_SIZE = getenv_str("ASR_MODEL_SIZE", "base")
