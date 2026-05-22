"""Risk metrics for the portfolio.

Все методы устойчивы к пустым/частично пустым данным и возвращают
0.0 / пустую структуру, если посчитать невозможно. Это нужно, чтобы
weekly-PDF не падал, если по какому-то тикеру нет истории.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

import pandas as pd

from src.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


class RiskAnalytics:
    def __init__(self, market_client: MarketDataClient) -> None:
        self.market = market_client
        self._logger = get_logger("risk")

    # ---------- Beta ----------

    def calculate_beta(
        self,
        positions: list[Position],
        benchmark: str = "SPY",
        period: str = "1y",
    ) -> float:
        bench_returns = self._daily_returns(benchmark, period)
        if bench_returns.empty:
            return 0.0

        weighted_beta = 0.0
        total_weight = 0.0
        for pos in positions:
            returns = self._daily_returns(pos.ticker, period)
            if returns.empty:
                continue
            aligned = pd.concat([returns, bench_returns], axis=1).dropna()
            if len(aligned) < 10:
                continue
            cov = aligned.cov().iloc[0, 1]
            var = bench_returns.var()
            if var == 0:
                continue
            beta = float(cov / var)
            weight = max(pos.market_value or pos.total_cost or 1.0, 1.0)
            weighted_beta += beta * weight
            total_weight += weight

        if total_weight == 0:
            return 0.0
        return weighted_beta / total_weight

    # ---------- Correlations ----------

    def calculate_correlations(
        self,
        positions: list[Position],
        period: str = "3mo",
    ) -> pd.DataFrame:
        frames = {}
        for pos in positions:
            returns = self._daily_returns(pos.ticker, period)
            if not returns.empty:
                frames[pos.ticker] = returns
        if not frames:
            return pd.DataFrame()
        combined = pd.concat(frames.values(), axis=1, keys=frames.keys()).dropna()
        if combined.empty:
            return pd.DataFrame()
        return combined.corr()

    # ---------- Drawdown ----------

    def calculate_max_drawdown(
        self,
        positions: list[Position],
        period: str = "1y",
    ) -> dict:
        # Build a synthetic portfolio value time series.
        series = self._portfolio_value_series(positions, period)
        if series.empty:
            return {"drawdown_percent": 0.0, "peak_date": None, "trough_date": None}

        running_max = series.cummax()
        drawdown = (series - running_max) / running_max
        min_dd_idx = drawdown.idxmin()
        min_dd = float(drawdown.loc[min_dd_idx])
        peak_idx = running_max.loc[:min_dd_idx].idxmax()
        return {
            "drawdown_percent": min_dd * 100.0,
            "peak_date": peak_idx.strftime("%Y-%m-%d") if hasattr(peak_idx, "strftime") else str(peak_idx),
            "trough_date": min_dd_idx.strftime("%Y-%m-%d") if hasattr(min_dd_idx, "strftime") else str(min_dd_idx),
        }

    # ---------- VaR ----------

    def calculate_var(
        self,
        positions: list[Position],
        confidence: float = 0.95,
        period_days: int = 1,
    ) -> float:
        series = self._portfolio_value_series(positions, period="3mo")
        if series.empty:
            return 0.0
        returns = series.pct_change().dropna()
        if returns.empty:
            return 0.0
        quantile = returns.quantile(1.0 - confidence)
        # Approx single-day VaR in USD on current portfolio value.
        current_value = float(series.iloc[-1])
        return float(abs(quantile) * current_value * math.sqrt(period_days))

    # ---------- Concentration ----------

    def calculate_concentration(self, positions: list[Position]) -> dict:
        values = [
            (pos.ticker, pos.market_value or pos.total_cost or 0.0)
            for pos in positions
        ]
        total = sum(v for _, v in values)
        if total == 0:
            return {"top_3_share": 0.0, "by_sector": {}, "hhi": 0.0}

        ranked = sorted(values, key=lambda x: x[1], reverse=True)
        top_3 = sum(v for _, v in ranked[:3]) / total

        sector_share: dict[str, float] = {}
        for pos in positions:
            value = pos.market_value or pos.total_cost or 0.0
            sector = pos.sector or "Unknown"
            sector_share[sector] = sector_share.get(sector, 0.0) + value
        sector_share = {k: v / total for k, v in sector_share.items()}

        # Herfindahl-Hirschman index on positions (0…1, higher = more concentrated).
        hhi = sum((v / total) ** 2 for _, v in values)

        return {
            "top_3_share": top_3,
            "top_position": ranked[0] if ranked else None,
            "by_sector": dict(sorted(sector_share.items(), key=lambda x: x[1], reverse=True)),
            "hhi": hhi,
        }

    # ---------- Helpers ----------

    def _daily_returns(self, ticker: str, period: str) -> pd.Series:
        hist = self.market.get_price_history(ticker, period=period, interval="1d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            return pd.Series(dtype=float)
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return pd.Series(dtype=float)
        return closes.pct_change().dropna()

    def _portfolio_value_series(
        self,
        positions: list[Position],
        period: str,
    ) -> pd.Series:
        series_list: list[pd.Series] = []
        for pos in positions:
            hist = self.market.get_price_history(pos.ticker, period=period, interval="1d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            qty = pos.quantity or 1.0
            series_list.append((hist["Close"].dropna() * qty).rename(pos.ticker))
        if not series_list:
            return pd.Series(dtype=float)
        joined = pd.concat(series_list, axis=1).ffill().fillna(0.0)
        return joined.sum(axis=1)
