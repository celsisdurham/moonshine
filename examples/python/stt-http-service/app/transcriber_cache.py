"""LRU cache of Transcriber instances with per-handle locking."""

from __future__ import annotations

import os
import threading
from collections import OrderedDict
from typing import Dict, Optional, Tuple

from moonshine_voice import Transcriber, get_model_for_language


class TranscriberCache:
    """
    One Transcriber per (language, word_timestamps), with a lock for native calls.

    Eviction closes the least-recently-used transcriber when over capacity.
    """

    def __init__(self, max_entries: int = 4) -> None:
        self._max = max(1, max_entries)
        self._data: OrderedDict[Tuple[str, bool], Tuple[Transcriber, threading.Lock]] = (
            OrderedDict()
        )
        self._guard = threading.Lock()

    def get(self, language: str, word_timestamps: bool) -> Tuple[Transcriber, threading.Lock]:
        key = (language, word_timestamps)
        with self._guard:
            if key in self._data:
                self._data.move_to_end(key)
                return self._data[key]

            while len(self._data) >= self._max:
                _, (old_t, _) = self._data.popitem(last=False)
                old_t.close()

            opts: Optional[Dict[str, str]] = (
                {"word_timestamps": "true"} if word_timestamps else None
            )
            model_path, model_arch = get_model_for_language(language)
            t = Transcriber(model_path, model_arch, options=opts)
            lock = threading.Lock()
            self._data[key] = (t, lock)
            return self._data[key]

    def close_all(self) -> None:
        with self._guard:
            for _, (t, _) in self._data.items():
                t.close()
            self._data.clear()


def default_cache() -> TranscriberCache:
    raw = os.environ.get("MOONSHINE_CACHE_MAX_ENTRIES", "4")
    try:
        n = int(raw)
    except ValueError:
        n = 4
    return TranscriberCache(max_entries=n)
