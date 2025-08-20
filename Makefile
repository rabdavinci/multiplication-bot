.PHONY: build up down logs restart clean

build:
	docker-compose build

up:
	docker-compose up -d

down:
	docker-compose down

logs:
	docker-compose logs -f

restart:
	docker-compose restart

clean:
	docker-compose down -v
	docker system prune -f

migrate:
	docker-compose exec multiplication-bot python -c "from bot import init_database; init_database()"

backup:
	cp data/multiplication_game.db data/multiplication_game_backup_$$(date +%Y%m%d_%H%M%S).db