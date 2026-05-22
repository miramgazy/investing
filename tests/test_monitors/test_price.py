"""PriceMonitor tests (no network — yfinance is fully stubbed)."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd

from src.monitors.price import PriceMonitor, _severity_for_change


def _cfg(threshold: float = 3.0, benchmark: str = "SPY"):
    return SimpleNamespace(
        monitoring=SimpleNamespace(price_movements=True),
        thresholds=SimpleNamespace(price_movement_percent=threshold),
        reports=SimpleNamespace(benchmark=benchmark),
    )


@dataclass
class _FakePosition:
    ticker: str


class _FakeMarket:
    def __init__(self, changes: dict[str, float]):
        self.changes = changes

    def get_price_history(self, ticker, period="5d", interval="1d"):
        change = self.changes.get(ticker, 0.0)
        # Build a 2-row frame so _daily_change_percent works.
        base = 100.0
        return pd.DataFrame({"Close": [base, base * (1 + change / 100)]})


def test_severity_buckets():
    assert _severity_for_change(2.0) == "medium"  # below threshold of 3 — outside check
    assert _severity_for_change(4.5) == "medium"
    assert _severity_for_change(-7.0) == "high"
    assert _severity_for_change(15.0) == "critical"


def test_signals_emitted_above_threshold_with_context():
    market = _FakeMarket({"AAPL": -7.2, "TSLA": 0.5, "SPY": -0.4})
    cfg = _cfg(threshold=3.0)
    monitor = PriceMonitor(cfg, market)
    signals = monitor.check([_FakePosition("AAPL"), _FakePosition("TSLA")])

    assert len(signals) == 1
    sig = signals[0]
    assert sig.ticker == "AAPL"
    assert sig.severity == "high"
    assert sig.data["benchmark"] == "SPY"
    # Relative strength = -7.2 - (-0.4) = -6.8
    assert sig.data["relative_strength"] == sig.data["change_percent"] - sig.data["benchmark_change_percent"]


def test_no_signals_when_change_below_threshold():
    market = _FakeMarket({"AAPL": 2.0, "SPY": 0.0})
    cfg = _cfg(threshold=3.0)
    monitor = PriceMonitor(cfg, market)
    signals = monitor.check([_FakePosition("AAPL")])
    assert signals == []


def test_history_fetch_error_does_not_raise():
    class Broken:
        def get_price_history(self, *a, **kw):
            raise RuntimeError("yfinance down")

    cfg = _cfg(threshold=1.0)
    monitor = PriceMonitor(cfg, Broken())
    assert monitor.check([_FakePosition("AAPL")]) == []
