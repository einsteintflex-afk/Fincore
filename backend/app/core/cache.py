"""Tiny per-process TTL cache for rarely-changing configuration (fee rules, limit rules, settings).

Values must be immutable snapshots (never ORM objects bound to a session). Admin edits call ``clear()`` so the
editing process sees changes immediately; other processes pick them up within ``ttl`` seconds.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

_lock = threading.Lock()
_store: dict[Any, tuple[float, Any]] = {}
CONFIG_TTL = 30.0


def get_or_load(key: Any, loader: Callable[[], Any], ttl: float = CONFIG_TTL) -> Any:
    now = time.monotonic()
    with _lock:
        hit = _store.get(key)
        if hit and hit[0] > now:
            return hit[1]
    value = loader()
    with _lock:
        _store[key] = (now + ttl, value)
    return value


def clear() -> None:
    with _lock:
        _store.clear()
