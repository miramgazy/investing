"""Wrapper around ``yfinance`` with retry, in-memory TTL cache and graceful
fallbacks.

yfinance иногда возвращает пустые данные, иногда стреляет таймаутами,
а у нас 7+ мониторов, которые могут параллельно дёргать одни и те же
тикеры. Лёгкий TTL-кеш в памяти и retry — то, что нужно.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

import pandas as pd
import yfinance as yf
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger


@dataclass
class _CacheEntry:
    value: Any
    expires_at: float


class MarketDataClient:
    """yfinance facade with retry and a tiny per-call TTL cache."""

    def __init__(self, cache_ttl: int = 300) -> None:
        self._ttl = cache_ttl
        self._cache: dict[str, _CacheEntry] = {}
        self._logger = get_logger("market_data")

    # ---------- Prices ----------

    def get_current_price(self, ticker: str) -> float:
        """Last known closing price for ``ticker``. Returns 0.0 if unavailable."""
        cached = self._get_cache(("price", ticker))
        if cached is not None:
            return cached

        hist = self.get_price_history(ticker, period="5d", interval="1d")
        if hist is None or hist.empty:
            return 0.0
        price = float(hist["Close"].iloc[-1])
        self._set_cache(("price", ticker), price)
        return price

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=8),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
        reraise=False,
    )
    def get_price_history(
        self,
        ticker: str,
        period: str = "1mo",
        interval: str = "1d",
    ) -> pd.DataFrame:
        """Return a ``DataFrame`` with OHLCV columns or an empty frame on error."""
        key = ("history", ticker, period, interval)
        cached = self._get_cache(key)
        if cached is not None:
            return cached

        try:
            data = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=False)
        except Exception as exc:
            self._logger.warning("yfinance history failed for %s: %s", ticker, exc)
            return pd.DataFrame()

        if data is None:
            data = pd.DataFrame()
        self._set_cache(key, data)
        return data

    def batch_get_prices(self, tickers: list[str]) -> dict[str, float]:
        """Best-effort bulk current-price lookup. Missing tickers map to 0.0."""
        if not tickers:
            return {}
        unique = sorted({t.strip().upper() for t in tickers if t and t.strip()})
        joined = " ".join(unique)
        try:
            data = yf.download(
                tickers=joined,
                period="5d",
                interval="1d",
                group_by="ticker",
                progress=False,
                threads=True,
                auto_adjust=False,
            )
        except Exception as exc:
            self._logger.warning("yfinance batch download failed: %s", exc)
            return {t: 0.0 for t in unique}

        out: dict[str, float] = {}
        for ticker in unique:
            try:
                if len(unique) == 1:
                    close = data["Close"].dropna()
                else:
                    close = data[ticker]["Close"].dropna()
                out[ticker] = float(close.iloc[-1]) if not close.empty else 0.0
            except (KeyError, IndexError, TypeError):
                out[ticker] = 0.0
        return out

    # ---------- Metadata / fundamentals ----------

    def get_company_info(self, ticker: str) -> dict:
        """sector / industry / market_cap / beta / pe_ratio / dividend_yield."""
        key = ("info", ticker)
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        try:
            info = yf.Ticker(ticker).info or {}
        except Exception as exc:
            self._logger.warning("yfinance info failed for %s: %s", ticker, exc)
            info = {}
        normalized = {
            "sector": info.get("sector", ""),
            "industry": info.get("industry", ""),
            "market_cap": info.get("marketCap"),
            "beta": info.get("beta"),
            "pe_ratio": info.get("trailingPE"),
            "dividend_yield": info.get("dividendYield"),
            "long_name": info.get("longName") or info.get("shortName", ""),
        }
        self._set_cache(key, normalized)
        return normalized

    # ---------- News & analysts ----------

    def get_recent_news(self, ticker: str, days: int = 1) -> list[dict]:
        """Return yfinance news entries from the last ``days`` days."""
        key = ("news", ticker, days)
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        try:
            raw = yf.Ticker(ticker).news or []
        except Exception as exc:
            self._logger.warning("yfinance news failed for %s: %s", ticker, exc)
            return []

        cutoff = time.time() - days * 86400
        filtered: list[dict] = []
        for item in raw:
            ts = item.get("providerPublishTime") or 0
            if ts >= cutoff:
                filtered.append(
                    {
                        "title": item.get("title", ""),
                        "publisher": item.get("publisher", ""),
                        "link": item.get("link", ""),
                        "ts": ts,
                    }
                )
        self._set_cache(key, filtered)
        return filtered

    def get_recommendations(self, ticker: str) -> pd.DataFrame:
        """Analyst recommendations DataFrame, or empty frame on error."""
        key = ("recs", ticker)
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        try:
            df = yf.Ticker(ticker).recommendations
        except Exception as exc:
            self._logger.warning("yfinance recommendations failed for %s: %s", ticker, exc)
            df = None
        if df is None:
            df = pd.DataFrame()
        self._set_cache(key, df)
        return df

    def get_earnings_calendar(self, ticker: str) -> dict:
        """Return a normalized earnings-calendar dict for ``ticker``."""
        key = ("earnings", ticker)
        cached = self._get_cache(key)
        if cached is not None:
            return cached
        try:
            calendar = yf.Ticker(ticker).calendar
        except Exception as exc:
            self._logger.warning("yfinance calendar failed for %s: %s", ticker, exc)
            calendar = None

        normalized: dict = {}
        if isinstance(calendar, dict):
            normalized = calendar
        elif hasattr(calendar, "to_dict"):
            # Older yfinance returned DataFrame; new one — dict.
            try:
                normalized = calendar.to_dict()
            except Exception:
                normalized = {}
        self._set_cache(key, normalized)
        return normalized

    def get_options_chain(self, ticker: str) -> dict:
        """Stub left intentionally light — future-proofing for Pro tier."""
        try:
            t = yf.Ticker(ticker)
            expirations = list(getattr(t, "options", []) or [])
        except Exception:
            expirations = []
        return {"expirations": expirations}

    # ---------- Cache ----------

    def _get_cache(self, key: tuple) -> Any:
        entry = self._cache.get(repr(key))
        if entry is None or entry.expires_at < time.time():
            return None
        return entry.value

    def _set_cache(self, key: tuple, value: Any) -> None:
        self._cache[repr(key)] = _CacheEntry(value=value, expires_at=time.time() + self._ttl)
