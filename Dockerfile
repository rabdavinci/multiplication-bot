FROM python:3.11-slim-bullseye

WORKDIR /app

# Копирование requirements сначала для кэширования
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копирование остальных файлов
COPY . .

# Создаем директорию для данных
RUN mkdir -p data && chmod 777 data

# Запуск бота
CMD ["python", "bot.py"]