"""RiskAnalytics tests."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import pytest

from src.analytics.risk import RiskAnalytics


@dataclass
class _Pos:
    ticker: str
    quantity: float = 1
    average_cost: float = 100
    market_value: float = 100
    sector: str = ""

    @property
    def total_cost(self) -> float:
        return self.quantity * self.average_cost


class _FakeMarket:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_price_history(self, ticker, period="1mo", interval="1d"):
        return self.mapping.get(ticker, pd.DataFrame())


def _close_series(values):
    idx = pd.date_range("2026-01-01", periods=len(values), freq="D")
    return pd.DataFrame({"Close": values}, index=idx)


def test_calculate_concentration_top3_share():
    positions = [
        _Pos("A", market_value=5000, sector="Tech"),
        _Pos("B", market_value=3000, sector="Tech"),
        _Pos("C", market_value=2000, sector="Healthcare"),
        _Pos("D", market_value=1000, sector="Energy"),
    ]
    out = RiskAnalytics(_FakeMarket({})).calculate_concentration(positions)
    # Top-3 = (5000+3000+2000) / 11000 ≈ 0.909
    assert out["top_3_share"] == pytest.approx((5000 + 3000 + 2000) / 11_000, rel=1e-3)
    assert out["by_sector"]["Tech"] == pytest.approx(8000 / 11_000, rel=1e-3)
    assert out["hhi"] > 0


def test_calculate_beta_returns_approximately_one_for_clone_of_benchmark():
    # Build artificial price series where AAPL == SPY exactly → beta == 1.
    rng = np.random.default_rng(seed=42)
    returns = rng.normal(0, 0.01, 250)
    closes = 100 * (1 + returns).cumprod()
    series = _close_series(closes)
    market = _FakeMarket({"AAPL": series, "SPY": series})
    beta = RiskAnalytics(market).calculate_beta(
        [_Pos("AAPL", market_value=1000)], benchmark="SPY"
    )
    assert beta == pytest.approx(1.0, abs=1e-6)


def test_correlations_dataframe_shape():
    # Build two anti-correlated *return* series. Using monotonic price series
    # would not work — pct_change of [1,2,3,4,5] vs [5,4,3,2,1] still produces
    # same-sign deltas after the first step. Use a deliberately reversed
    # return pattern instead.
    rng = np.random.default_rng(seed=7)
    base = rng.normal(0, 0.01, 200)
    prices_a = 100 * (1 + base).cumprod()
    prices_b = 100 * (1 - base).cumprod()  # daily returns are exact opposites
    market = _FakeMarket(
        {"A": _close_series(prices_a.tolist()), "B": _close_series(prices_b.tolist())}
    )
    corr = RiskAnalytics(market).calculate_correlations([_Pos("A"), _Pos("B")])
    assert corr.shape == (2, 2)
    # Daily returns of A and B are negatives of each other ⇒ correlation ≈ -1.
    assert corr.loc["A", "B"] < -0.9


def test_max_drawdown_basic():
    # Crash sequence: 100 → 120 → 60 → 90 (drawdown = -50% from 120 to 60).
    market = _FakeMarket({"X": _close_series([100, 120, 60, 90])})
    out = RiskAnalytics(market).calculate_max_drawdown([_Pos("X", quantity=1)])
    assert out["drawdown_percent"] == pytest.approx(-50.0, abs=0.1)


def test_concentration_empty():
    out = RiskAnalytics(_FakeMarket({})).calculate_concentration([])
    assert out["top_3_share"] == 0.0
    assert out["hhi"] == 0.0
