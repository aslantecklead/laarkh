from redis import Redis
from app.config import REDIS_HOST, REDIS_PORT, REDIS_DB


def get_redis() -> Redis:
    return Redis(host=REDIS_HOST, port=REDIS_PORT, db=REDIS_DB, decode_responses=True)