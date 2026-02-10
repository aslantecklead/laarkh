import asyncio
import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from redis.asyncio import Redis
from redis.exceptions import ConnectionError as RedisConnectionError

# Загружаем переменные окружения при импорте модуля
load_dotenv()

log = logging.getLogger("app.redis")


class InMemoryRedis:
    def __init__(self) -> None:
        self._store: Dict[str, Tuple[Any, Optional[float]]] = {}
        self._lock = threading.Lock()

    def _purge_expired(self, key: str) -> None:
        value = self._store.get(key)
        if value is None:
            return
        _, expires_at = value
        if expires_at is not None and expires_at <= time.time():
            self._store.pop(key, None)

    def ping(self) -> bool:
        return True

    def get(self, name: str) -> Optional[str]:
        with self._lock:
            self._purge_expired(name)
            value = self._store.get(name)
            if value is None:
                return None
            return value[0]

    def set(self, name: str, value: Any, ex: Optional[int] = None, px: Optional[int] = None, nx: bool = False) -> bool:
        if ex is not None and px is not None:
            raise ValueError("ex and px are mutually exclusive")
        expires_at = None
        if ex is not None:
            expires_at = time.time() + int(ex)
        elif px is not None:
            expires_at = time.time() + (int(px) / 1000.0)
        with self._lock:
            self._purge_expired(name)
            if nx and name in self._store:
                return False
            self._store[name] = (value, expires_at)
            return True

    def setex(self, name: str, time_seconds: int, value: Any) -> bool:
        return self.set(name, value, ex=time_seconds)

    def delete(self, *names: str) -> int:
        removed = 0
        with self._lock:
            for name in names:
                self._purge_expired(name)
                if name in self._store:
                    self._store.pop(name, None)
                    removed += 1
        return removed

    def exists(self, name: str) -> int:
        with self._lock:
            self._purge_expired(name)
            return 1 if name in self._store else 0

    def incr(self, name: str) -> int:
        with self._lock:
            self._purge_expired(name)
            value, expires_at = self._store.get(name, ("0", None))
            try:
                number = int(value)
            except (TypeError, ValueError):
                number = 0
            number += 1
            self._store[name] = (str(number), expires_at)
            return number

    def ttl(self, name: str) -> int:
        with self._lock:
            self._purge_expired(name)
            value = self._store.get(name)
            if value is None:
                return -2
            _, expires_at = value
            if expires_at is None:
                return -1
            return max(0, int(expires_at - time.time()))


_in_memory_client = InMemoryRedis()


class AsyncInMemoryRedis:
    def __init__(self, backend: InMemoryRedis) -> None:
        self._backend = backend

    async def ping(self) -> bool:
        return self._backend.ping()

    async def get(self, name: str) -> Optional[str]:
        return self._backend.get(name)

    async def set(self, name: str, value: Any, ex: Optional[int] = None, px: Optional[int] = None, nx: bool = False) -> bool:
        return self._backend.set(name, value, ex=ex, px=px, nx=nx)

    async def setex(self, name: str, time_seconds: int, value: Any) -> bool:
        return self._backend.setex(name, time_seconds, value)

    async def delete(self, *names: str) -> int:
        return self._backend.delete(*names)

    async def exists(self, name: str) -> int:
        return self._backend.exists(name)

    async def incr(self, name: str) -> int:
        return self._backend.incr(name)

    async def ttl(self, name: str) -> int:
        return self._backend.ttl(name)


class AsyncResilientRedis:
    def __init__(self, redis_client: Redis, fallback_client: AsyncInMemoryRedis) -> None:
        self._redis = redis_client
        self._fallback = fallback_client
        self._use_fallback = False

    def _switch_to_fallback(self) -> None:
        if not self._use_fallback:
            log.warning("Redis unavailable; falling back to in-memory cache.")
            self._use_fallback = True

    async def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._use_fallback:
            return await getattr(self._fallback, method)(*args, **kwargs)
        try:
            return await getattr(self._redis, method)(*args, **kwargs)
        except RedisConnectionError:
            self._switch_to_fallback()
            return await getattr(self._fallback, method)(*args, **kwargs)

    async def ping(self) -> bool:
        return bool(await self._call("ping"))

    async def get(self, name: str) -> Optional[str]:
        return await self._call("get", name)

    async def set(self, name: str, value: Any, ex: Optional[int] = None, px: Optional[int] = None, nx: bool = False) -> bool:
        return bool(await self._call("set", name, value, ex=ex, px=px, nx=nx))

    async def setex(self, name: str, time_seconds: int, value: Any) -> bool:
        return bool(await self._call("setex", name, time_seconds, value))

    async def delete(self, *names: str) -> int:
        return int(await self._call("delete", *names))

    async def exists(self, name: str) -> int:
        return int(await self._call("exists", name))

    async def incr(self, name: str) -> int:
        return int(await self._call("incr", name))

    async def ttl(self, name: str) -> int:
        return int(await self._call("ttl", name))


_client_instances: Dict[int, AsyncResilientRedis] = {}


def _loop_key() -> int:
    try:
        loop = asyncio.get_running_loop()
        return id(loop)
    except RuntimeError:
        return -1


def get_redis_client() -> AsyncResilientRedis:
    key = _loop_key()
    client = _client_instances.get(key)
    if client is None:
        redis_client = Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
            socket_connect_timeout=5,
            decode_responses=True,
        )
        client = AsyncResilientRedis(redis_client, AsyncInMemoryRedis(_in_memory_client))
        _client_instances[key] = client
    return client
