"""Signal-deduplication cache backed by a JSON file in ``data/``.

Каждый сигнал имеет стабильный :pymeth:`Signal.unique_id` — мы храним эти
идентификаторы вместе с timestamp'ом отправки и считаем сигнал "уже
отправленным", пока ему не исполнится ``ttl_days`` дней.

Cache-файл коммитится в git (см. ``.gitignore``) — это и есть способ
переносить состояние между запусками GitHub Actions.
"""

from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

from src.constants import PATH_SENT_SIGNALS
from src.monitors.base import Signal
from src.utils.logger import get_logger


class SignalDeduplicator:
    """Persistent dedup cache for outgoing signals."""

    def __init__(
        self,
        cache_file: str | Path = PATH_SENT_SIGNALS,
        ttl_days: int = 7,
    ) -> None:
        self.cache_file = Path(cache_file)
        self.ttl_seconds = ttl_days * 86400
        self._logger = get_logger("dedup")
        self._cache: dict[str, dict] = self._load_cache()
        # Cleanup on startup so the cache file doesn't grow indefinitely.
        self.cleanup_old()

    # ---------- Public API ----------

    def is_already_sent(self, signal: Signal) -> bool:
        entry = self._cache.get(signal.unique_id())
        if entry is None:
            return False
        return entry.get("expires_at", 0) > time.time()

    def mark_sent(self, signal: Signal) -> None:
        self._cache[signal.unique_id()] = {
            "signal_type": signal.signal_type,
            "ticker": signal.ticker,
            "severity": signal.severity,
            "title": signal.title,
            "sent_at": datetime.now().isoformat(),
            "expires_at": time.time() + self.ttl_seconds,
        }
        self._save_cache()

    def filter_new(self, signals: list[Signal]) -> list[Signal]:
        return [s for s in signals if not self.is_already_sent(s)]

    def cleanup_old(self) -> None:
        before = len(self._cache)
        now = time.time()
        self._cache = {k: v for k, v in self._cache.items() if v.get("expires_at", 0) > now}
        if len(self._cache) != before:
            self._save_cache()

    def signals_in_window(self, days: int) -> list[dict]:
        """Return signal metadata sent in the last ``days`` days. Used by the weekly PDF."""
        cutoff = time.time() - days * 86400
        out = []
        for entry in self._cache.values():
            sent_at_iso = entry.get("sent_at")
            if not sent_at_iso:
                continue
            try:
                sent_at = datetime.fromisoformat(sent_at_iso).timestamp()
            except ValueError:
                continue
            if sent_at >= cutoff:
                out.append(entry)
        return out

    # ---------- I/O ----------

    def _load_cache(self) -> dict[str, dict]:
        if not self.cache_file.exists():
            return {}
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._logger.warning("Could not read sent_signals cache: %s", exc)
            return {}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
        except OSError as exc:
            self._logger.warning("Could not write sent_signals cache: %s", exc)
