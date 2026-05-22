"""Portfolio performance metrics.

Все методы возвращают примитивы (dict / float). Сетевые вызовы делегированы
:class:`MarketDataClient` — здесь только арифметика.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import numpy as np
import pandas as pd

from src.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


_PERIOD_TO_YFINANCE = {
    "1d": "5d",
    "1w": "1mo",
    "1mo": "3mo",
    "3mo": "6mo",
    "6mo": "1y",
    "1y": "1y",
}


class PerformanceAnalytics:
    def __init__(self, market_client: MarketDataClient) -> None:
        self.market = market_client
        self._logger = get_logger("performance")

    # ---------- Returns ----------

    def calculate_returns(
        self, positions: list[Position], period: str = "1w"
    ) -> dict:
        per_position: dict[str, dict] = {}
        total_start = 0.0
        total_end = 0.0

        for pos in positions:
            hist = self.market.get_price_history(
                pos.ticker, period=_PERIOD_TO_YFINANCE.get(period, period), interval="1d"
            )
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 2:
                continue
            start_price = float(closes.iloc[0])
            end_price = float(closes.iloc[-1])
            qty = pos.quantity or 1.0  # для fallback-режима без CSV qty=0
            per_position[pos.ticker] = {
                "start_price": start_price,
                "end_price": end_price,
                "return_percent": (end_price / start_price - 1.0) * 100.0,
                "return_usd": (end_price - start_price) * qty,
            }
            if pos.quantity:
                total_start += start_price * pos.quantity
                total_end += end_price * pos.quantity

        total_return_percent = (
            (total_end / total_start - 1.0) * 100.0 if total_start else 0.0
        )

        return {
            "total_return_percent": total_return_percent,
            "total_return_usd": total_end - total_start,
            "total_start": total_start,
            "total_end": total_end,
            "by_position": per_position,
        }

    # ---------- Vs benchmark ----------

    def compare_to_benchmark(
        self,
        positions: list[Position],
        benchmark: str = "SPY",
        period: str = "1w",
    ) -> dict:
        portfolio = self.calculate_returns(positions, period)
        bench_hist = self.market.get_price_history(
            benchmark, period=_PERIOD_TO_YFINANCE.get(period, period), interval="1d"
        )
        bench_return = 0.0
        if bench_hist is not None and not bench_hist.empty and "Close" in bench_hist.columns:
            closes = bench_hist["Close"].dropna()
            if len(closes) >= 2:
                bench_return = (float(closes.iloc[-1]) / float(closes.iloc[0]) - 1.0) * 100.0

        return {
            "portfolio_return": portfolio["total_return_percent"],
            "benchmark_return": bench_return,
            "benchmark_ticker": benchmark,
            "alpha": portfolio["total_return_percent"] - bench_return,
            "outperformance": portfolio["total_return_percent"] - bench_return,
        }

    # ---------- Sharpe ----------

    def calculate_sharpe_ratio(
        self,
        positions: list[Position],
        risk_free_rate: float = 0.04,
        period: str = "1y",
    ) -> float:
        # Build a daily-return series for the weighted portfolio.
        all_returns: list[pd.Series] = []
        weights: list[float] = []
        for pos in positions:
            hist = self.market.get_price_history(
                pos.ticker, period=_PERIOD_TO_YFINANCE.get(period, period), interval="1d"
            )
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 5:
                continue
            returns = closes.pct_change().dropna()
            all_returns.append(returns)
            weights.append(max(pos.market_value or pos.total_cost or 1.0, 1.0))

        if not all_returns:
            return 0.0

        combined = pd.concat(all_returns, axis=1).fillna(0.0)
        weights_arr = np.array(weights, dtype=float)
        weights_arr /= weights_arr.sum()
        portfolio_returns = combined.values @ weights_arr

        excess = portfolio_returns - (risk_free_rate / 252)
        std = excess.std(ddof=0)
        if std == 0 or math.isnan(std):
            return 0.0
        # Annualize.
        return float((excess.mean() / std) * math.sqrt(252))

    # ---------- Movers ----------

    def get_top_movers(
        self,
        positions: list[Position],
        period: str = "1w",
        n: int = 3,
    ) -> dict:
        returns = self.calculate_returns(positions, period)["by_position"]
        ranked = sorted(
            returns.items(), key=lambda x: x[1]["return_percent"], reverse=True
        )
        leaders = [(ticker, data["return_percent"]) for ticker, data in ranked[:n]]
        leader_tickers = {ticker for ticker, _ in leaders}
        # Аутсайдеры берутся из НИЖНЕЙ части ranked, и мы исключаем тикеры, уже
        # попавшие в лидеры — иначе для портфелей <2n позиций таблицы пересекались бы.
        laggards: list[tuple[str, float]] = []
        for ticker, data in reversed(ranked):
            if ticker in leader_tickers:
                continue
            laggards.append((ticker, data["return_percent"]))
            if len(laggards) == n:
                break
        return {"leaders": leaders, "laggards": laggards}
