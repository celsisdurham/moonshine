# Speech-to-text sidecar: HTTP batch + WebSocket streaming (Moonshine Voice).
# See docs/shared-stt-http-service.md

FROM python:3.12-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    libsndfile1 \
    && rm -rf /var/lib/apt/lists/*

RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

RUN mkdir -p /data/moonshine_voice && chown 1000:1000 /data/moonshine_voice

USER appuser
ENV MOONSHINE_LANGUAGE=en
ENV PORT=8080
ENV MOONSHINE_VOICE_CACHE=/data/moonshine_voice
EXPOSE 8080

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
