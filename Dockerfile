# Shared image for every service. Build context is the repo root (see docker-compose.yml).
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
