import os
import time
from functools import wraps
from fastapi import Request, Response
from starlette.responses import JSONResponse
from app.infrastructure.cache.redis_client import get_redis_client

# Получаем клиент Redis
redis_client = get_redis_client()

# Значения по умолчанию
DEFAULT_RATE_LIMIT_MAX_REQUESTS = 5
DEFAULT_RATE_LIMIT_WINDOW = 60

def get_env_variable(var_name: str, default: any = None):
    """Получить переменную окружения, преобразовав ее в нужный тип"""
    value = os.getenv(var_name)
    if value is None:
        return default
    # Преобразуем в int если значение числовое
    if value.isdigit():
        return int(value)
    return value

def rate_limit(max_requests=None, window=None, by_ip=True):
    def decorator(f):
        @wraps(f)
        async def decorated_function(*args, **kwargs):
            # Получаем актуальные значения из переменных окружения при каждом вызове
            actual_max_requests = max_requests or get_env_variable('RATE_LIMIT_MAX_REQUESTS', DEFAULT_RATE_LIMIT_MAX_REQUESTS)
            actual_window = window or get_env_variable('RATE_LIMIT_WINDOW', DEFAULT_RATE_LIMIT_WINDOW)
            
            # Извлекаем request из kwargs (FastAPI)
            fastapi_request = kwargs.get('fastapi_request')
            if not fastapi_request:
                return JSONResponse(
                    status_code=400,
                    content={"error": "Request object is required"}
                )
            
            # Choose identifier based on IP or video_id
            if by_ip:
                # Получаем IP из headers
                x_forwarded_for = fastapi_request.headers.get('x-forwarded-for')
                if x_forwarded_for:
                    identifier = x_forwarded_for.split(',')[0].strip()
                else:
                    identifier = fastapi_request.client.host if fastapi_request.client else 'unknown'
                key = f"rate_limit:{identifier}"
            else:
                # If not by IP, we expect video_id in request body
                body = await fastapi_request.json()
                video_id = body.get('video_id')
                if not video_id:
                    return JSONResponse(
                        status_code=400,
                        content={"error": "video_id is required for rate limiting"}
                    )
                key = f"rate_limit:{video_id}"

            current = redis_client.get(key)
            
            if current is None:
                # Set initial counter with expiration
                pipe = redis_client.pipeline()
                pipe.setex(key, actual_window, 1)
                pipe.execute()
            elif int(current) >= actual_max_requests:
                return JSONResponse(
                    status_code=429,
                    content={"error": "Rate limit exceeded. Try again later."}
                )
            else:
                redis_client.incr(key)
            
            return await f(*args, **kwargs)
        return decorated_function
    return decorator
