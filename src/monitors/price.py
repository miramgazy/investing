"""Price-movement monitor with S&P 500 context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.monitors.base import BaseMonitor, Signal
from src.utils.formatting import format_percent

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


class PriceMonitor(BaseMonitor):
    name = "Price Movement Monitor"
    config_flag = "price_movements"

    def __init__(self, config, market_client: MarketDataClient) -> None:
        super().__init__(config)
        self.market = market_client
        self.threshold = config.thresholds.price_movement_percent
        self.benchmark = config.reports.benchmark or "SPY"

    def check(self, positions: list[Position]) -> list[Signal]:
        if not positions:
            return []

        # Получаем историю одной серией — кеш помогает, и yfinance не нагружаем.
        tickers = sorted({p.ticker for p in positions} | {self.benchmark})
        history_by_ticker: dict[str, float] = {}
        for ticker in tickers:
            try:
                hist = self.market.get_price_history(ticker, period="5d", interval="1d")
                history_by_ticker[ticker] = _daily_change_percent(hist)
            except Exception as exc:
                self.logger.warning("History fetch failed for %s: %s", ticker, exc)
                history_by_ticker[ticker] = 0.0

        market_change = history_by_ticker.get(self.benchmark, 0.0)

        signals: list[Signal] = []
        for position in positions:
            change = history_by_ticker.get(position.ticker, 0.0)
            if abs(change) < self.threshold:
                continue
            signals.append(self._make_signal(position, change, market_change))
        return signals

    def _make_signal(self, position, change: float, market_change: float) -> Signal:
        severity = _severity_for_change(change)
        direction = "вырос" if change > 0 else "упал"
        relative = change - market_change
        title = (
            f"{position.ticker}: {direction} на {format_percent(change, with_sign=False)}"
        )
        description = (
            f"${position.ticker} {direction} на {format_percent(change)}.\n"
            f"S&P 500 ({self.benchmark}): {format_percent(market_change)}.\n"
            f"Относительно рынка: {format_percent(relative)}."
        )
        return Signal(
            signal_type="price",
            ticker=position.ticker,
            severity=severity,
            title=title[:80],
            description=description,
            data={
                "change_percent": change,
                "benchmark": self.benchmark,
                "benchmark_change_percent": market_change,
                "relative_strength": relative,
            },
        )


def _daily_change_percent(hist) -> float:
    """Return last-day closing change in percent. 0.0 on missing data."""
    if hist is None or len(hist) < 2 or "Close" not in hist.columns:
        return 0.0
    closes = hist["Close"].dropna()
    if len(closes) < 2:
        return 0.0
    return (float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1.0) * 100.0


def _severity_for_change(change: float) -> str:
    a = abs(change)
    if a >= 10:
        return "critical"
    if a >= 5:
        return "high"
    return "medium"
