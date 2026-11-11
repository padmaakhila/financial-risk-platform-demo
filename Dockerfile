
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    bash tesseract-ocr curl && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home app && \
    mkdir -p /app/data && \
    chmod +x /app/start_render.sh && \
    chown -R app:app /app/data

USER app

EXPOSE 10000

CMD ["bash", "/app/start_render.sh"]
