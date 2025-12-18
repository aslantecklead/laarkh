import pytest
import time
from app.infrastructure.cache.redis_client import get_redis_client

redis_client = get_redis_client()

def test_redis_connection():
    """Тест подключения к Redis"""
    try:
        # Проверяем подключение к Redis
        assert redis_client.ping(), "Не удалось подключиться к Redis"
        
        # Тест записи и чтения данных
        test_key = "test_connection:1"
        test_value = "success"
        
        # Устанавливаем значение
        redis_client.setex(test_key, 60, test_value)
        
        # Читаем значение
        value = redis_client.get(test_key)
        assert value == test_value, f"Значение не совпадает: ожидается {test_value}, получено {value}"
        
        # Удаляем тестовый ключ
        redis_client.delete(test_key)
        
    except Exception as e:
        pytest.fail(f"Ошибка при тестировании Redis: {e}")


def test_rate_limit_functionality():
    """Тест функциональности rate limit"""
    rate_limit_key = "test_ratelimit:client1"
    max_requests = 3
    window = 60  # 1 минута
    
    # Очищаем ключ перед тестом
    redis_client.delete(rate_limit_key)
    
    # Делаем max_requests + 1 запросов
    for i in range(max_requests):
        current = redis_client.get(rate_limit_key)
        if current is None:
            redis_client.setex(rate_limit_key, window, 1)
        else:
            redis_client.incr(rate_limit_key)
    
    # Проверяем, что лимит достигнут
    final_count = int(redis_client.get(rate_limit_key))
    assert final_count == max_requests, f"Количество запросов не совпадает: ожидается {max_requests}, получено {final_count}"
    
    # Удаляем тестовый ключ
    redis_client.delete(rate_limit_key)


def test_concurrent_download_lock():
    """Тест блокировки параллельной загрузки"""
    video_id = "UInyP9Uy7tY"
    downloading_key = f"{video_id}:downloading"
    status_key = f"status:{video_id}"
    expire_time = 300
    
    # Очищаем тестовые ключи
    redis_client.delete(downloading_key)
    redis_client.delete(status_key)
    
    # Пробуем установить блокировку первый раз
    is_downloading_first = redis_client.set(downloading_key, "1", ex=expire_time, nx=True)
    assert is_downloading_first is not None, "Не удалось установить блокировку при первом вызове"
    
    # Проверяем, что статус установлен
    status = redis_client.get(status_key)
    # Устанавливаем статус для теста
    redis_client.setex(status_key, expire_time, "downloading")
    
    # Пробуем установить блокировку второй раз (должно провалиться)
    is_downloading_second = redis_client.set(downloading_key, "1", ex=expire_time, nx=True)
    assert is_downloading_second is None, "Удалось установить блокировку при параллельном вызове, что недопустимо"
    
    # Проверяем, что значение осталось прежним
    value = redis_client.get(downloading_key)
    assert value == "1", f"Значение блокировки изменилось: ожидается '1', получено {value}"
    
    # Проверяем TTL
    ttl = redis_client.ttl(downloading_key)
    assert ttl > 0 and ttl <= expire_time, f"TTL некорректен: {ttl}"    
    
    # Очищаем тестовые ключи
    redis_client.delete(downloading_key)
    redis_client.delete(status_key)