"""Earnings calendar monitor.

Шлёт сигналы за ``earnings_days_before`` дней до публикации (low/medium)
и в день публикации (high).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from src.monitors.base import BaseMonitor, Signal

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


class EarningsMonitor(BaseMonitor):
    name = "Earnings Calendar Monitor"
    config_flag = "earnings"

    def __init__(self, config, market_client: MarketDataClient) -> None:
        super().__init__(config)
        self.market = market_client
        self.days_before = config.thresholds.earnings_days_before

    def check(self, positions: list[Position]) -> list[Signal]:
        signals: list[Signal] = []
        for position in positions:
            try:
                cal = self.market.get_earnings_calendar(position.ticker)
                upcoming = self._parse_calendar(cal)
                if upcoming is None:
                    continue
                sig = self._make_signal(position.ticker, upcoming, cal)
                if sig:
                    signals.append(sig)
            except Exception as exc:
                self.logger.error("Earnings check failed for %s: %s", position.ticker, exc)
        return signals

    # ---------- Helpers ----------

    def _parse_calendar(self, cal: dict) -> date | None:
        """Pull the next earnings date from yfinance's calendar dict, if any."""
        if not cal:
            return None
        # New yfinance: cal["Earnings Date"] = [datetime, ...]
        candidates = cal.get("Earnings Date") or cal.get("earningsDate") or []
        if isinstance(candidates, dict):
            candidates = list(candidates.values())
        if not isinstance(candidates, list):
            candidates = [candidates]
        for raw in candidates:
            d = _coerce_date(raw)
            if d is None:
                continue
            if d >= date.today():
                return d
        return None

    def _make_signal(self, ticker: str, earnings_date: date, cal: dict) -> Signal | None:
        days_to = (earnings_date - date.today()).days
        if days_to < 0 or days_to > self.days_before:
            # Outside the alert window — skip.
            return None

        severity = "high" if days_to == 0 else ("medium" if days_to <= 1 else "low")
        eps_estimate = _first_value(cal.get("Earnings Average")) or _first_value(cal.get("epsEstimate"))
        rev_estimate = _first_value(cal.get("Revenue Average")) or _first_value(cal.get("revenueEstimate"))
        when = "сегодня" if days_to == 0 else f"через {days_to} {_days_word(days_to)}"

        return Signal(
            signal_type="earnings",
            ticker=ticker,
            severity=severity,
            title=f"{ticker}: earnings {when}"[:80],
            description=(
                f"Earnings publication: {earnings_date.isoformat()}.\n"
                f"EPS estimate: {eps_estimate or '—'}\n"
                f"Revenue estimate: {rev_estimate or '—'}"
            ),
            data={
                "date": earnings_date.isoformat(),
                "days_to": days_to,
                "eps_estimate": eps_estimate,
                "revenue_estimate": rev_estimate,
            },
        )


def _coerce_date(value) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        # YYYY-MM-DD is 10 chars; strip any trailing time portion if present.
        head = value[:10] if len(value) >= 10 else value
        try:
            return datetime.strptime(head, "%Y-%m-%d").date()
        except ValueError:
            pass
    # yfinance иногда возвращает pandas Timestamp — у них есть .date()
    if hasattr(value, "date"):
        try:
            return value.date()
        except Exception:
            return None
    return None


def _first_value(obj):
    if obj is None:
        return None
    if isinstance(obj, dict):
        for v in obj.values():
            if v is not None:
                return v
    if isinstance(obj, list) and obj:
        return obj[0]
    return obj


def _days_word(n: int) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return "день"
    if n % 10 in {2, 3, 4} and n % 100 not in {12, 13, 14}:
        return "дня"
    return "дней"
