FROM python:3.11-slim-bullseye

# Установка системных зависимостей
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Создание пользователя для безопасности
RUN useradd --create-home --shell /bin/bash botuser
WORKDIR /app
RUN chown botuser:botuser /app

# Копирование requirements сначала для кэширования
COPY --chown=botuser:botuser requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копирование остальных файлов
COPY --chown=botuser:botuser . .

# Переключение на непривилегированного пользователя
USER botuser

# Создание директорий для данных и логов
RUN mkdir -p data logs

# Запуск бота
CMD ["python", "bot.py"]