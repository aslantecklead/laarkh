# app/main.py
from fastapi import FastAPI
from app.infrastructure.asr.factory import initialize_asr
from app.infrastructure.cache.video_catalog_refresher import start_video_catalog_refresher
from app.api.subtitles import router as subtitles_router
from app.api.cookies import router as cookies_router
from app.api.activity import router as activity_router
from app.api.sessions import router as sessions_router
from app.api.videos import router as videos_router
from app.api.updates import router as updates_router
from app.infrastructure.db.indexes import ensure_indexes
import logging
import threading

logger = logging.getLogger(__name__)

app = FastAPI(
    title="Linguada API",
    description="Fast YouTube subtitle generation service",
    version="2.0.0"
)

# Включаем роутер
app.include_router(subtitles_router)
app.include_router(cookies_router)
app.include_router(activity_router)
app.include_router(sessions_router)
app.include_router(videos_router)
app.include_router(updates_router)


@app.on_event("startup")
async def startup_event():
    """Startup event - предзагрузка моделей"""
    logger.info("Starting Linguada API v2.0...")
    try:
        await ensure_indexes()
        logger.info("MongoDB indexes ensured")
    except Exception as e:
        logger.error(f"Failed to ensure MongoDB indexes: {e}")

    # Запускаем предзагрузку моделей в фоновом режиме
    def preload_models_background():
        try:
            initialize_asr()
            logger.info("✓ Models preloaded successfully")
        except Exception as e:
            logger.error(f"Failed to preload models: {e}")

    # Запускаем в отдельном потоке чтобы не блокировать старт
    thread = threading.Thread(target=preload_models_background, daemon=True)
    thread.start()
    logger.info("Model preloading started in background...")

    try:
        start_video_catalog_refresher()
        logger.info("Video catalog cache refresher started")
    except Exception as e:
        logger.error(f"Failed to start video catalog cache refresher: {e}")


@app.get("/")
async def root():
    """Root endpoint with health check"""
    return {
        "service": "Linguada Subtitle Generator",
        "version": "2.0.0",
        "status": "running",
        "features": ["YouTube subtitle generation", "Fast CPU processing", "Model caching"]
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "linguada"}
