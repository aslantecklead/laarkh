import os
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient


_client: Optional[AsyncIOMotorClient] = None


def get_mongo_client() -> AsyncIOMotorClient:
    global _client
    if _client is None:
        uri = os.getenv("MONGO_URI", "mongodb://admin:admin@localhost:27017/linguada?authSource=admin")
        _client = AsyncIOMotorClient(uri)
    return _client


def get_mongo_db():
    db_name = os.getenv("MONGO_DB", "linguada")
    return get_mongo_client()[db_name]


def get_common_user_id() -> str:
    return os.getenv("COMMON_USER_ID", "public")


async def ensure_common_user() -> str:
    user_id = get_common_user_id()
    db = get_mongo_db()
    users = db["users"]
    existing = await users.find_one({"_id": user_id})
    if not existing:
        now = __import__("datetime").datetime.utcnow()
        await users.insert_one(
            {
                "_id": user_id,
                "username": "public",
                "created_at": now,
                "updated_at": now,
            }
        )
    return user_id
