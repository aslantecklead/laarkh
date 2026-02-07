import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    reload_enabled = os.getenv("RELOAD").lower() == "true"
    workers = int(os.getenv("WEB_CONCURRENCY", "1"))
    if reload_enabled and workers > 1:
        workers = 1

    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST"),
        port=int(os.getenv("PORT")),
        reload=reload_enabled,
        log_level=os.getenv("LOG_LEVEL"),
        access_log=True,
        workers=workers,
    )
