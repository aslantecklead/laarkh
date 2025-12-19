import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent  # .../app

AUDIO_SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE"))
AUDIO_BITRATE = os.getenv("AUDIO_BITRATE")
AUDIO_CHANNELS = int(os.getenv("AUDIO_CHANNELS"))

MAX_CONCURRENT_DOWNLOADS = int(os.getenv("MAX_CONCURRENT_DOWNLOADS"))
MAX_AUDIO_DURATION = int(os.getenv("MAX_AUDIO_DURATION"))
DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_HOST = os.getenv("REDIS_HOST")
REDIS_PORT = int(os.getenv("REDIS_PORT"))
REDIS_DB = int(os.getenv("REDIS_DB"))
ASR_MODEL_SIZE = os.getenv("ASR_MODEL_SIZE", "small")
