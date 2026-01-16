# app/main.py
from fastapi import FastAPI
from app.infrastructure.asr.factory import initialize_asr
from app.api.subtitles import router as subtitles_router
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


@app.on_event("startup")
async def startup_event():
    """Startup event - предзагрузка моделей"""
    logger.info("Starting Linguada API v2.0...")

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