import os
from redis import Redis
from dotenv import load_dotenv

# Загружаем переменные окружения при импорте модуля
load_dotenv()


def get_redis_client() -> Redis:
    return Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        socket_connect_timeout=5,
        decode_responses=True
    )
