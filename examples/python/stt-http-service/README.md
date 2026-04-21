# STT HTTP / WebSocket service (example)

Reference implementation of a **shared Moonshine STT microservice** for multiple clients on a Docker network.

Full architecture, API details, and security notes: **[docs/shared-stt-http-service.md](../../docs/shared-stt-http-service.md)**.

## Run locally

```bash
cd examples/python/stt-http-service
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8080
```

## Docker

```bash
docker build -t moonshine-stt examples/python/stt-http-service
docker run --rm -p 8080:8080 -v moonshine-models:/data/moonshine_voice moonshine-stt
```

The image sets `MOONSHINE_VOICE_CACHE=/data/moonshine_voice` so model downloads persist when you mount that path.

**Compose** (from this directory):

```bash
docker compose up --build
```

## Environment

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | `8080` | Listen port (Docker `CMD` uses this) |
| `MOONSHINE_LANGUAGE` | `en` | Default language when the client omits one |
| `MOONSHINE_VOICE_CACHE` | _(platform default)_ | Model download directory; set to `/data/moonshine_voice` in the example image |
| `MOONSHINE_CACHE_MAX_ENTRIES` | `4` | Max cached `(language, word_timestamps)` transcriber instances |
| `MOONSHINE_CORS_ORIGINS` | _(empty)_ | Comma-separated origins; if set, CORS is enabled for the API |

## Quick checks

```bash
curl -s http://127.0.0.1:8080/health
```

Batch transcribe (replace with a real WAV path):

```bash
curl -s -X POST http://127.0.0.1:8080/v1/transcribe \
  -F "audio=@/path/to/file.wav" \
  -F "language=en" \
  -F "word_timestamps=false"
```
