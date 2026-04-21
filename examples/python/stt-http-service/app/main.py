"""FastAPI STT service: batch HTTP and streaming WebSocket."""

from __future__ import annotations

import asyncio
import json
import os
import struct
import tempfile
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from moonshine_voice.errors import MoonshineError
from moonshine_voice.transcriber import (
    LineCompleted,
    LineStarted,
    LineTextChanged,
    LineUpdated,
    TranscriptEventListener,
)
from moonshine_voice.utils import load_wav_file

from app.serialization import line_to_dict, transcript_lines_to_payload
from app.transcriber_cache import TranscriberCache, default_cache


def _default_language() -> str:
    return os.environ.get("MOONSHINE_LANGUAGE", "en").strip() or "en"


def _parse_bool(v: Optional[str]) -> bool:
    if v is None or str(v).strip() == "":
        return False
    return str(v).lower() in ("1", "true", "yes", "on")


def _float32_le_bytes_to_list(data: bytes) -> List[float]:
    n = len(data) // 4
    if n == 0:
        return []
    return list(struct.unpack(f"<{n}f", data[: n * 4]))


class _QueueListener(TranscriptEventListener):
    """Forwards Moonshine events to an async queue (thread-safe via call_soon_threadsafe)."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        outbound: asyncio.Queue,
    ) -> None:
        self._loop = loop
        self._outbound = outbound

    def _put(self, msg: Dict[str, Any]) -> None:
        self._loop.call_soon_threadsafe(self._outbound.put_nowait, msg)

    def on_line_started(self, event: LineStarted) -> None:
        self._put({"type": "line_started", "line": line_to_dict(event.line)})

    def on_line_updated(self, event: LineUpdated) -> None:
        self._put({"type": "line_updated", "line": line_to_dict(event.line)})

    def on_line_text_changed(self, event: LineTextChanged) -> None:
        self._put({"type": "line_text_changed", "line": line_to_dict(event.line)})

    def on_line_completed(self, event: LineCompleted) -> None:
        self._put({"type": "line_completed", "line": line_to_dict(event.line)})


@asynccontextmanager
async def lifespan(app: FastAPI):
    cache: TranscriberCache = default_cache()
    app.state.cache = cache
    yield
    cache.close_all()


app = FastAPI(title="Moonshine STT service", lifespan=lifespan)

_origins = os.environ.get("MOONSHINE_CORS_ORIGINS", "").strip()
if _origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.get("/health")
async def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/transcribe")
async def transcribe_batch(
    audio: UploadFile = File(..., description="WAV (16- or 24-bit PCM)"),
    language: Optional[str] = Form(None),
    word_timestamps: Optional[str] = Form(None),
) -> Dict[str, Any]:
    lang = (language or _default_language()).strip() or _default_language()
    wt = _parse_bool(word_timestamps)
    cache: TranscriberCache = app.state.cache
    transcriber, lock = cache.get(lang, wt)

    name = audio.filename or "upload.wav"
    suffix = os.path.splitext(name)[1] or ".wav"
    try:
        body = await audio.read()
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(body)
            path = tmp.name
        try:
            samples, sample_rate = load_wav_file(path)
        finally:
            os.unlink(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    try:
        with lock:
            transcript = transcriber.transcribe_without_streaming(samples, sample_rate)
    except MoonshineError as e:
        raise HTTPException(status_code=500, detail=str(e)) from e

    return {
        "language": lang,
        "sample_rate": sample_rate,
        "lines": transcript_lines_to_payload(transcript.lines),
    }


@app.websocket("/v1/transcribe/stream")
async def transcribe_stream(websocket: WebSocket) -> None:
    await websocket.accept()
    cache: TranscriberCache = app.state.cache
    loop = asyncio.get_running_loop()
    outbound: asyncio.Queue = asyncio.Queue()
    stream = None
    lock = None

    async def send_loop() -> None:
        while True:
            msg = await outbound.get()
            try:
                await websocket.send_json(msg)
            except Exception:
                return
            if msg.get("type") == "final":
                return

    send_task = asyncio.create_task(send_loop())

    try:
        try:
            try:
                raw = await websocket.receive_text()
            except WebSocketDisconnect:
                await outbound.put({"type": "final"})
                await send_task
                return
            try:
                cfg = json.loads(raw)
            except json.JSONDecodeError as e:
                await outbound.put({"type": "error", "detail": f"Invalid JSON: {e}"})
                await outbound.put({"type": "final"})
                await send_task
                return

            if cfg.get("type") != "config":
                await outbound.put(
                    {"type": "error", "detail": "First message must be config"}
                )
                await outbound.put({"type": "final"})
                await send_task
                return

            language = str(cfg.get("language") or _default_language()).strip() or _default_language()
            sample_rate = int(cfg.get("sample_rate", 16000))
            if sample_rate <= 0:
                raise ValueError("sample_rate must be positive")
            word_timestamps = bool(cfg.get("word_timestamps", False))
            update_interval = float(cfg.get("update_interval", 0.25))
            if update_interval <= 0:
                raise ValueError("update_interval must be positive")
        except (ValueError, TypeError) as e:
            await outbound.put({"type": "error", "detail": str(e)})
            await outbound.put({"type": "final"})
            await send_task
            return

        try:
            transcriber, lock = cache.get(language, word_timestamps)
        except Exception as e:
            await outbound.put({"type": "error", "detail": str(e)})
            await outbound.put({"type": "final"})
            await send_task
            return

        listener = _QueueListener(loop, outbound)

        try:
            stream = transcriber.create_stream(update_interval=update_interval)
            stream.add_listener(listener)
            stream.start()
            await outbound.put(
                {"type": "ready", "language": language, "sample_rate": sample_rate}
            )

            while True:
                msg = await websocket.receive()
                if msg["type"] == "websocket.disconnect":
                    break
                if msg["type"] != "websocket.receive":
                    continue
                if msg.get("bytes"):
                    floats = _float32_le_bytes_to_list(msg["bytes"])
                    if floats:
                        try:
                            with lock:
                                stream.add_audio(floats, sample_rate)
                        except MoonshineError as e:
                            await outbound.put({"type": "error", "detail": str(e)})
                            break
                elif msg.get("text"):
                    try:
                        ctrl = json.loads(msg["text"])
                    except json.JSONDecodeError:
                        continue
                    if ctrl.get("type") == "end":
                        break
        except WebSocketDisconnect:
            pass
        except MoonshineError as e:
            await outbound.put({"type": "error", "detail": str(e)})
        except Exception as e:
            await outbound.put({"type": "error", "detail": str(e)})
        finally:
            if stream is not None and lock is not None:
                with lock:
                    try:
                        stream.stop()
                    except Exception:
                        pass
                    try:
                        stream.close()
                    except Exception:
                        pass
            await outbound.put({"type": "final"})
            await send_task
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
