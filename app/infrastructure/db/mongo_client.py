import os
from typing import Optional

from pymongo import MongoClient


_client: Optional[MongoClient] = None


def get_mongo_client() -> MongoClient:
    global _client
    if _client is None:
        uri = os.getenv("MONGO_URI", "mongodb://admin:admin@localhost:27017/linguada?authSource=admin")
        _client = MongoClient(uri)
    return _client


def get_mongo_db():
    db_name = os.getenv("MONGO_DB", "linguada")
    return get_mongo_client()[db_name]


def get_common_user_id() -> str:
    return os.getenv("COMMON_USER_ID", "public")


def ensure_common_user() -> str:
    user_id = get_common_user_id()
    db = get_mongo_db()
    users = db["users"]
    existing = users.find_one({"_id": user_id})
    if not existing:
        users.insert_one(
            {
                "_id": user_id,
                "username": "public",
                "created_at": __import__("datetime").datetime.utcnow(),
                "updated_at": __import__("datetime").datetime.utcnow(),
            }
        )
    return user_id
