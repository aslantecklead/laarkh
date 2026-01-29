import logging
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from dotenv import load_dotenv
from redis import Redis
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


class ResilientRedis:
    def __init__(self, redis_client: Redis, fallback_client: InMemoryRedis) -> None:
        self._redis = redis_client
        self._fallback = fallback_client
        self._use_fallback = False

    def _switch_to_fallback(self) -> None:
        if not self._use_fallback:
            log.warning("Redis unavailable; falling back to in-memory cache.")
            self._use_fallback = True

    def _call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        if self._use_fallback:
            return getattr(self._fallback, method)(*args, **kwargs)
        try:
            return getattr(self._redis, method)(*args, **kwargs)
        except RedisConnectionError:
            self._switch_to_fallback()
            return getattr(self._fallback, method)(*args, **kwargs)

    def ping(self) -> bool:
        return bool(self._call("ping"))

    def get(self, name: str) -> Optional[str]:
        return self._call("get", name)

    def set(self, name: str, value: Any, ex: Optional[int] = None, px: Optional[int] = None, nx: bool = False) -> bool:
        return bool(self._call("set", name, value, ex=ex, px=px, nx=nx))

    def setex(self, name: str, time_seconds: int, value: Any) -> bool:
        return bool(self._call("setex", name, time_seconds, value))

    def delete(self, *names: str) -> int:
        return int(self._call("delete", *names))

    def exists(self, name: str) -> int:
        return int(self._call("exists", name))

    def incr(self, name: str) -> int:
        return int(self._call("incr", name))

    def ttl(self, name: str) -> int:
        return int(self._call("ttl", name))


_client_instance: Optional[ResilientRedis] = None


def get_redis_client() -> ResilientRedis:
    global _client_instance
    if _client_instance is None:
        redis_client = Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=int(os.getenv("REDIS_DB", 0)),
            socket_connect_timeout=5,
            decode_responses=True,
        )
        _client_instance = ResilientRedis(redis_client, _in_memory_client)
        try:
            _client_instance.ping()
        except RedisConnectionError:
            _client_instance._switch_to_fallback()
    return _client_instance
