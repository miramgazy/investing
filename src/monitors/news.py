"""News monitor with Claude-based importance scoring.

Каждый заголовок оценивается на 1–10. Чтобы не тратить токены повторно,
оценки кешируются в ``data/news_cache.json``.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.constants import PATH_NEWS_CACHE
from src.monitors.base import BaseMonitor, Signal

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.claude import ClaudeClient
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


_CACHE_TTL_SECONDS = 7 * 86400  # 7 дней
_TOKEN_RE = re.compile(r"[a-zа-яё0-9$]+", re.IGNORECASE)


class NewsMonitor(BaseMonitor):
    name = "News Monitor"
    config_flag = "news"

    def __init__(
        self,
        config,
        market_client: MarketDataClient,
        claude_client: ClaudeClient,
        cache_file: str | Path = PATH_NEWS_CACHE,
    ) -> None:
        super().__init__(config)
        self.market = market_client
        self.claude = claude_client
        self.threshold = config.thresholds.news_importance_min
        self.cache_file = Path(cache_file)
        self._cache = self._load_cache()

    def check(self, positions: list[Position]) -> list[Signal]:
        signals: list[Signal] = []
        try:
            for position in positions:
                try:
                    raw_news = self.market.get_recent_news(position.ticker, days=1)
                except Exception as exc:
                    self.logger.warning("News fetch failed for %s: %s", position.ticker, exc)
                    continue
                if not raw_news:
                    continue
                for news in self._deduplicate_news(raw_news):
                    sig = self._maybe_signal(position.ticker, news)
                    if sig:
                        signals.append(sig)
        finally:
            self._save_cache()

        return signals

    # ---------- Helpers ----------

    def _maybe_signal(self, ticker: str, news: dict) -> Signal | None:
        news_id = _news_id(ticker, news)
        cached = self._cache.get(news_id)
        if cached and cached.get("expires_at", 0) > time.time():
            score = int(cached["score"])
            reason = cached.get("reason", "")
        else:
            try:
                score, reason = self.claude.score_importance(news.get("title", ""), ticker)
            except Exception as exc:
                self.logger.warning("Claude scoring failed: %s", exc)
                return None
            self._cache[news_id] = {
                "score": score,
                "reason": reason,
                "expires_at": time.time() + _CACHE_TTL_SECONDS,
            }

        if score < self.threshold:
            return None

        severity = _severity_for_score(score)
        return Signal(
            signal_type="news",
            ticker=ticker,
            severity=severity,
            title=f"{ticker}: {news.get('title', 'Новость')}"[:80],
            description=(
                f"<b>{news.get('publisher', '')}</b>: {news.get('title', '')}\n\n"
                f"<i>Оценка Claude:</i> {score}/10 — {reason}"
            ),
            data={
                "score": score,
                "reason": reason,
                "publisher": news.get("publisher", ""),
                "title": news.get("title", ""),
            },
            timestamp=datetime.fromtimestamp(news.get("ts") or time.time()),
            source_url=news.get("link", ""),
        )

    def _deduplicate_news(self, items: list[dict]) -> list[dict]:
        """Drop near-duplicates (≥70% token overlap on title)."""
        seen: list[set[str]] = []
        out: list[dict] = []
        for item in items:
            tokens = _tokenize(item.get("title", ""))
            if not tokens:
                continue
            if any(_jaccard(tokens, prev) >= 0.7 for prev in seen):
                continue
            seen.append(tokens)
            out.append(item)
        return out

    def _load_cache(self) -> dict[str, dict]:
        if not self.cache_file.exists():
            return {}
        try:
            raw = json.loads(self.cache_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        # Drop expired entries on load.
        now = time.time()
        return {k: v for k, v in raw.items() if v.get("expires_at", 0) > now}

    def _save_cache(self) -> None:
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps(self._cache, indent=2, ensure_ascii=False), encoding="utf-8"
            )
        except OSError as exc:
            self.logger.warning("Could not persist news cache: %s", exc)


# ---------- Module-level helpers ----------


def _severity_for_score(score: int) -> str:
    if score >= 10:
        return "critical"
    if score >= 9:
        return "high"
    return "medium"


def _news_id(ticker: str, news: dict) -> str:
    raw = f"{ticker}|{news.get('title', '')}|{news.get('publisher', '')}".encode()
    return hashlib.sha1(raw).hexdigest()[:16]


def _tokenize(text: str) -> set[str]:
    return {tok.lower() for tok in _TOKEN_RE.findall(text or "") if len(tok) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0
