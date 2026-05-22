"""Analyst rating change monitor based on yfinance recommendations."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import pandas as pd

from src.monitors.base import BaseMonitor, Signal

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


# Whitelist'ы — включают как длинные, так и короткие написания.
MAJOR_BANKS: set[str] = {
    "goldman sachs", "goldman", "gs",
    "morgan stanley", "ms",
    "jpmorgan", "jp morgan", "jpm",
    "bank of america", "bofa", "bac", "merrill lynch", "merrill",
    "citi", "citigroup",
    "barclays",
    "wells fargo", "wfc",
    "deutsche bank", "db",
    "ubs",
    "credit suisse",
    "wedbush",
    "jefferies",
    "evercore",
    "cowen",
    "piper sandler",
}

_DOWNGRADE_KEYWORDS = {"sell", "underweight", "underperform", "negative"}
_UPGRADE_KEYWORDS = {"buy", "overweight", "outperform", "positive", "strong buy"}


class AnalystMonitor(BaseMonitor):
    name = "Analyst Ratings Monitor"
    config_flag = "analyst_ratings"

    def __init__(self, config, market_client: MarketDataClient) -> None:
        super().__init__(config)
        self.market = market_client

    def check(self, positions: list[Position]) -> list[Signal]:
        signals: list[Signal] = []
        cutoff = datetime.now() - timedelta(days=1)

        for position in positions:
            try:
                df = self.market.get_recommendations(position.ticker)
                if df is None or df.empty:
                    continue
                recent = _filter_recent(df, cutoff)
                if recent.empty:
                    continue
                for _, row in recent.iterrows():
                    firm = str(row.get("Firm", "")).strip()
                    if not _is_major_bank(firm):
                        continue
                    sig = self._row_to_signal(position.ticker, row, firm)
                    if sig:
                        signals.append(sig)
            except Exception as exc:
                self.logger.error("Analyst check failed for %s: %s", position.ticker, exc)

        return signals

    # ---------- Helpers ----------

    def _row_to_signal(
        self, ticker: str, row: pd.Series, firm: str
    ) -> Signal | None:
        to_grade = str(row.get("To Grade", row.get("ToGrade", ""))).strip()
        from_grade = str(row.get("From Grade", row.get("FromGrade", ""))).strip()
        action = str(row.get("Action", "")).strip().lower()

        direction = _direction(action, from_grade, to_grade)
        if direction is None:
            return None

        severity = {
            "downgrade": "high",
            "upgrade": "medium",
            "initiated_buy": "medium",
            "initiated_sell": "high",
        }.get(direction, "medium")

        title_map = {
            "downgrade": f"{ticker}: понижение от {firm}",
            "upgrade": f"{ticker}: повышение от {firm}",
            "initiated_buy": f"{ticker}: новое покрытие — Buy ({firm})",
            "initiated_sell": f"{ticker}: новое покрытие — Sell ({firm})",
        }
        title = title_map.get(direction, f"{ticker}: рейтинг от {firm}")

        return Signal(
            signal_type="analyst",
            ticker=ticker,
            severity=severity,
            title=title[:80],
            description=(
                f"Аналитики {firm} изменили рейтинг по ${ticker}: "
                f"{from_grade or '?'} → {to_grade or '?'} ({direction})."
            ),
            data={
                "firm": firm,
                "from_grade": from_grade,
                "to_grade": to_grade,
                "action": action,
                "direction": direction,
            },
        )


def _filter_recent(df: pd.DataFrame, cutoff: datetime) -> pd.DataFrame:
    """Filter recommendations DataFrame to entries strictly after ``cutoff``."""
    if df.index.dtype.kind == "M":  # datetime index
        return df[df.index >= cutoff]
    for col in ("Date", "date", "GradeDate"):
        if col in df.columns:
            ts = pd.to_datetime(df[col], errors="coerce")
            return df[ts >= cutoff]
    # No usable timestamp → assume all are fresh enough; ratings tab on yfinance
    # already returns recent items.
    return df


def _is_major_bank(firm: str) -> bool:
    if not firm:
        return False
    f = firm.lower()
    return any(brand in f for brand in MAJOR_BANKS)


def _direction(action: str, from_grade: str, to_grade: str) -> str | None:
    a = action.lower()
    if a == "init" or a == "initiated":
        if any(k in to_grade.lower() for k in _UPGRADE_KEYWORDS):
            return "initiated_buy"
        if any(k in to_grade.lower() for k in _DOWNGRADE_KEYWORDS):
            return "initiated_sell"
        return None
    if a == "down" or "downgrade" in a:
        return "downgrade"
    if a == "up" or "upgrade" in a:
        return "upgrade"
    # Fallback по сравнению грейдов.
    if from_grade and to_grade and from_grade != to_grade:
        if any(k in to_grade.lower() for k in _DOWNGRADE_KEYWORDS):
            return "downgrade"
        if any(k in to_grade.lower() for k in _UPGRADE_KEYWORDS):
            return "upgrade"
    return None
