from fastapi import FastAPI

from app.api.subtitles import router as subtitles_router

app = FastAPI(title="MVP YouTube Subtitles Generator")

app.include_router(subtitles_router)

@app.get("/health")
def health():
    return {
        "ok": True,
        "service": "subtitles_generator",
        "target_audio": {
            "codec": "opus",
            "channels": 1,
            "sample_rate": 16000,
            "bitrate": "8k",
            "application": "lowdelay"
        },
    }