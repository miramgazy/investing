"""PerformanceAnalytics tests with stubbed yfinance frames."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from src.analytics.performance import PerformanceAnalytics


@dataclass
class _Pos:
    ticker: str
    quantity: float = 0
    average_cost: float = 0
    market_value: float = 0

    @property
    def total_cost(self) -> float:
        return self.quantity * self.average_cost


class _FakeMarket:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_price_history(self, ticker, period="1mo", interval="1d"):
        return self.mapping.get(ticker, pd.DataFrame())


def _series(*values: float) -> pd.DataFrame:
    return pd.DataFrame({"Close": list(values)})


def test_calculate_returns_weighted_by_quantity():
    market = _FakeMarket(
        {
            "AAPL": _series(100, 110),  # +10%
            "TSLA": _series(200, 180),  # -10%
        }
    )
    perf = PerformanceAnalytics(market).calculate_returns(
        [_Pos("AAPL", quantity=10), _Pos("TSLA", quantity=5)], period="1w"
    )
    # AAPL contributes 10*100=1000 → 1100; TSLA contributes 5*200=1000 → 900.
    assert perf["total_start"] == pytest.approx(2000)
    assert perf["total_end"] == pytest.approx(2000)
    assert perf["total_return_percent"] == pytest.approx(0.0)
    assert perf["by_position"]["AAPL"]["return_percent"] == pytest.approx(10.0)
    assert perf["by_position"]["TSLA"]["return_percent"] == pytest.approx(-10.0)


def test_compare_to_benchmark_alpha():
    market = _FakeMarket(
        {
            "AAPL": _series(100, 115),  # +15%
            "SPY": _series(100, 105),  # +5%
        }
    )
    out = PerformanceAnalytics(market).compare_to_benchmark(
        [_Pos("AAPL", quantity=10)], benchmark="SPY", period="1w"
    )
    assert out["portfolio_return"] == pytest.approx(15.0)
    assert out["benchmark_return"] == pytest.approx(5.0)
    assert out["alpha"] == pytest.approx(10.0)


def test_get_top_movers():
    market = _FakeMarket(
        {
            "A": _series(100, 105),  # +5%
            "B": _series(100, 110),  # +10%
            "C": _series(100, 90),   # -10%
        }
    )
    movers = PerformanceAnalytics(market).get_top_movers(
        [_Pos("A"), _Pos("B"), _Pos("C")], n=2
    )
    leader_tickers = [t for t, _ in movers["leaders"]]
    laggard_tickers = [t for t, _ in movers["laggards"]]
    assert leader_tickers[0] == "B"
    assert laggard_tickers[0] == "C"


def test_get_top_movers_no_duplicate_tickers_in_small_portfolio():
    """Regression: для портфеля из <2n позиций лидеры и аутсайдеры
    не должны пересекаться. Раньше один и тот же тикер мог попасть в обе колонки."""
    market = _FakeMarket(
        {
            "A": _series(100, 110),
            "B": _series(100, 105),
            "C": _series(100, 102),
            "D": _series(100, 98),
            "E": _series(100, 90),
        }
    )
    movers = PerformanceAnalytics(market).get_top_movers(
        [_Pos(t) for t in "ABCDE"], n=3
    )
    leaders = {t for t, _ in movers["leaders"]}
    laggards = {t for t, _ in movers["laggards"]}
    assert leaders.isdisjoint(laggards), \
        f"Duplicate tickers in leaders+laggards: {leaders & laggards}"
