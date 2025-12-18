import pytest
import json
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from app.api.download import download_audio
from fastapi import Request

# Создаем mock объекты
mock_request = AsyncMock()
mock_use_case = AsyncMock()

# Создаем объект FastAPI Request для теста
from starlette.datastructures import Headers
from starlette.requests import Request as StarletteRequest

def create_test_request():
    # Создаем мок объекта Request
    mock_request = MagicMock()
    mock_request.headers = {"x-forwarded-for": "127.0.0.1"}
    mock_request.client = MagicMock()
    mock_request.client.host = "127.0.0.1"
    
    # Мокаем метод json()
    async def json_method():
        return {"url": "https://youtu.be/UInyP9Uy7tY?si=mWxa-xHGaLTIS4Uu", "video_id": "UInyP9Uy7tY"}
    
    mock_request.json = json_method
    return mock_request

def test_download_first_request():
    """Тест первого запроса на скачивание"""
    # Создаем тестовый request FastAPI
    test_request = create_test_request()
    
    # Мокаем use_case.execute для имитации успешного скачивания
    with patch('app.api.download.DownloadAudioUseCase') as mock_use_case_class:
        mock_use_case = mock_use_case_class.return_value
        mock_use_case.execute = AsyncMock(return_value={"id": "UInyP9Uy7tY", "url": "https://youtu.be/UInyP9Uy7tY"})
        
        # Вызываем тестируемую функцию
        result = asyncio.run(download_audio(
            request={"url": "https://youtu.be/UInyP9Uy7tY?si=mWxa-xHGaLTIS4Uu", "video_id": "UInyP9Uy7tY"},
            fastapi_request=test_request,
            use_case=mock_use_case
        ))
        
        # Проверяем результат
        assert result["ok"] is True
        assert result["video_id"] == "UInyP9Uy7tY"
        
        # Проверяем, что use_case.execute был вызван
        mock_use_case.execute.assert_called_once_with("https://youtu.be/UInyP9Uy7tY?si=mWxa-xHGaLTIS4Uu")

def test_download_parallel_request():
    """Тест параллельного запроса на скачивание (должен быть заблокирован)"""
    # Сначала имитируем первый запрос, который начинает скачивание
    with patch('app.api.download.get_redis_client') as mock_redis:
        # Настраиваем мок Redis клиента
        redis_instance = mock_redis.return_value
        redis_instance.set.return_value = True  # Первый запрос успешно устанавливает блокировку
        
        # Вызываем первый запрос (успешно)
        test_request = create_test_request()
        with patch('app.api.download.DownloadAudioUseCase') as mock_use_case_class:
            mock_use_case = mock_use_case_class.return_value
            mock_use_case.execute = AsyncMock(return_value={"id": "UInyP9Uy7tY", "url": "https://youtu.be/UInyP9Uy7tY"})
            
            result1 = asyncio.run(download_audio(
                request={"url": "https://youtu.be/UInyP9Uy7tY?si=mWxa-xHGaLTIS4Uu", "video_id": "UInyP9Uy7tY"},
                fastapi_request=test_request,
                use_case=mock_use_case
            ))
            
            assert result1["ok"] is True
            assert result1["video_id"] == "UInyP9Uy7tY"
    
    # Теперь имитируем параллельный запрос
    with patch('app.api.download.get_redis_client') as mock_redis:
        # Настраиваем мок Redis клиента - блокировка уже существует
        redis_instance = mock_redis.return_value
        redis_instance.set.return_value = None  # Указывает, что блокировка уже существует
        
        # Вызываем параллельный запрос (должен быть заблокирован)
        test_request = create_test_request()
        with patch('app.api.download.DownloadAudioUseCase') as mock_use_case_class:
            mock_use_case = mock_use_case_class.return_value
            
            try:
                result2 = asyncio.run(download_audio(
                    request={"url": "https://youtu.be/UInyP9Uy7tY?si=mWxa-xHGaLTIS4Uu", "video_id": "UInyP9Uy7tY"},
                    fastapi_request=test_request,
                    use_case=mock_use_case
                ))
                # Если мы дошли до этой точки, тест должен провалиться
                pytest.fail("Ожидалась ошибка 429 при параллельном запросе")
            except Exception as e:
                # Проверяем, что это HTTPException с кодом 429
                assert e.status_code == 429
                assert "Video is already being processed" in str(e.detail)