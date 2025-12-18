from fastapi import FastAPI

from app.api.download import router
from app.infrastructure.worker import AudioDownloader
from app.config import DOWNLOAD_DIR

app = FastAPI(title="MVP YouTube Audio Downloader (ASR-optimized)")

audio_downloader = AudioDownloader()

app.include_router(router)

@app.get("/health")
def health():
    return {
        "ok": True,
        "download_dir": str(DOWNLOAD_DIR),
        "target_audio": {
            "codec": "opus",
            "channels": 1,
            "sample_rate": 16000,
            "bitrate": "8k",
            "application": "lowdelay"
        },
    }