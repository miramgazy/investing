"""Ticker → CIK mapping with on-disk cache for SEC EDGAR.

SEC публикует полный mapping тикер→CIK в одном JSON-файле
(``company_tickers.json``). Скачивать его каждый запуск дорого и невежливо —
держим локальный кеш в ``data/cik_cache.json`` и обновляем не чаще раза в
неделю.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Final

import requests

from src.constants import DEFAULT_SEC_USER_AGENT, PATH_CIK_CACHE
from src.utils.logger import get_logger

_SEC_TICKERS_URL: Final = "https://www.sec.gov/files/company_tickers.json"
_CACHE_TTL: Final = timedelta(days=7)


class TickerUtils:
    """Persistent ticker ↔ CIK + company name lookups."""

    def __init__(
        self,
        cache_file: str | Path = PATH_CIK_CACHE,
        user_agent: str = DEFAULT_SEC_USER_AGENT,
    ) -> None:
        self._cache_file = Path(cache_file)
        self._user_agent = user_agent
        self._logger = get_logger("tickers")
        self._mapping: dict[str, dict] | None = None

    # ---------- Public API ----------

    def get_cik(self, ticker: str) -> str | None:
        """Return zero-padded 10-digit CIK for ``ticker`` or ``None``."""
        if not ticker:
            return None
        entry = self._mapping_lookup(ticker)
        if entry is None:
            return None
        cik = entry.get("cik_str")
        if cik is None:
            return None
        return str(cik).zfill(10)

    def get_company_name(self, ticker: str) -> str:
        """Return SEC's official company name for ``ticker`` (empty if unknown)."""
        entry = self._mapping_lookup(ticker)
        if entry is None:
            return ""
        return str(entry.get("title", ""))

    def validate_ticker(self, ticker: str) -> bool:
        """True if the ticker exists in SEC's mapping."""
        return self._mapping_lookup(ticker) is not None

    # ---------- Cache ----------

    def _mapping_lookup(self, ticker: str) -> dict | None:
        mapping = self._get_mapping()
        return mapping.get(ticker.strip().upper())

    def _get_mapping(self) -> dict[str, dict]:
        if self._mapping is not None:
            return self._mapping

        if self._is_cache_fresh():
            try:
                payload = json.loads(self._cache_file.read_text(encoding="utf-8"))
                self._mapping = payload
                return payload
            except (OSError, json.JSONDecodeError) as exc:
                self._logger.warning("CIK cache unreadable, refreshing: %s", exc)

        self._mapping = self._refresh_cache()
        return self._mapping

    def _is_cache_fresh(self) -> bool:
        if not self._cache_file.exists():
            return False
        age = datetime.now().timestamp() - self._cache_file.stat().st_mtime
        return age < _CACHE_TTL.total_seconds()

    def _refresh_cache(self) -> dict[str, dict]:
        self._logger.info("Refreshing SEC ticker → CIK mapping from %s", _SEC_TICKERS_URL)
        try:
            response = requests.get(
                _SEC_TICKERS_URL,
                headers={"User-Agent": self._user_agent, "Accept-Encoding": "gzip"},
                timeout=30,
            )
            response.raise_for_status()
            raw = response.json()
        except (requests.RequestException, ValueError) as exc:
            self._logger.error("Failed to refresh CIK cache: %s", exc)
            # Если есть стейл-кеш — лучше старые данные, чем никаких.
            if self._cache_file.exists():
                return json.loads(self._cache_file.read_text(encoding="utf-8"))
            return {}

        # Source format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
        mapping: dict[str, dict] = {}
        for entry in raw.values():
            ticker = str(entry.get("ticker", "")).upper().strip()
            if ticker:
                mapping[ticker] = entry

        self._cache_file.parent.mkdir(parents=True, exist_ok=True)
        self._cache_file.write_text(
            json.dumps(mapping, indent=2, sort_keys=True), encoding="utf-8"
        )
        # SEC rate-limit politeness: дадим короткую паузу после массивного скачивания.
        time.sleep(0.2)
        return mapping
