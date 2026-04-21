"""Serialize Moonshine transcript lines for JSON/WebSocket responses."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from moonshine_voice.moonshine_api import TranscriptLine, WordTiming


def word_timing_to_dict(w: WordTiming) -> Dict[str, Any]:
    return {
        "word": w.word,
        "start": w.start,
        "end": w.end,
        "confidence": w.confidence,
    }


def line_to_dict(line: TranscriptLine, *, include_audio_data: bool = False) -> Dict[str, Any]:
    """Convert a TranscriptLine to a JSON-serializable dict (omit heavy audio by default)."""
    words: Optional[List[Dict[str, Any]]] = None
    if line.words:
        words = [word_timing_to_dict(w) for w in line.words]

    out: Dict[str, Any] = {
        "text": line.text,
        "start_time": line.start_time,
        "duration": line.duration,
        "line_id": line.line_id,
        "is_complete": line.is_complete,
        "is_updated": line.is_updated,
        "is_new": line.is_new,
        "has_text_changed": line.has_text_changed,
        "has_speaker_id": line.has_speaker_id,
        "speaker_id": line.speaker_id,
        "speaker_index": line.speaker_index,
        "last_transcription_latency_ms": line.last_transcription_latency_ms,
        "words": words,
    }
    if include_audio_data and line.audio_data is not None:
        out["audio_data"] = line.audio_data
    return out


def transcript_lines_to_payload(lines: List[TranscriptLine]) -> List[Dict[str, Any]]:
    return [line_to_dict(line) for line in lines]
