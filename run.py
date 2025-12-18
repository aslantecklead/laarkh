import os
import uvicorn
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app",
        host=os.getenv("HOST"),
        port=int(os.getenv("PORT")),
        reload=os.getenv("RELOAD").lower() == "true",
        log_level=os.getenv("LOG_LEVEL"),
        access_log=True,
    )
