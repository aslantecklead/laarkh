.PHONY: build up down logs clean purge

# Имя образа
IMAGE_NAME = linguada:cpu-latest

# Сборка образа
build:
	@echo "🔨 Building CPU-optimized Linguada image..."
	docker build -f Dockerfile.cpu -t $(IMAGE_NAME) .
	@echo "📦 Image size:"
	@docker images $(IMAGE_NAME) --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"

# Запуск
up:
	docker-compose up -d

# Остановка
down:
	docker-compose down

# Логи
logs:
	docker-compose logs -f app

# Очистка временных файлов
clean:
	docker-compose down -v
	docker system prune -f

# Полная очистка
purge: clean
	docker rmi -f $(IMAGE_NAME) || true
	docker volume prune -f

# Пересборка и запуск
rebuild: build up

# Проверка здоровья
health:
	@curl -f http://localhost:8000/health || echo "Service is not healthy"

# Тестовый запрос
test:
	@echo "Testing API..."
	@curl -X POST http://localhost:8000/api/subtitles \
		-H "Content-Type: application/json" \
		-d '{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}' \
		-s | jq .