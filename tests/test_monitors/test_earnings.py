"""EarningsMonitor tests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from types import SimpleNamespace

from src.monitors.earnings import EarningsMonitor, _coerce_date


def _cfg(days_before: int = 3):
    return SimpleNamespace(
        monitoring=SimpleNamespace(earnings=True),
        thresholds=SimpleNamespace(earnings_days_before=days_before),
    )


@dataclass
class _FakePosition:
    ticker: str


class _FakeMarket:
    def __init__(self, calendars):
        self.calendars = calendars

    def get_earnings_calendar(self, ticker):
        return self.calendars.get(ticker, {})


def test_coerce_date_variants():
    today = date.today()
    assert _coerce_date(today) == today
    assert _coerce_date("2026-05-20") == date(2026, 5, 20)
    assert _coerce_date(None) is None


def test_signal_when_earnings_today_is_high():
    today = date.today()
    market = _FakeMarket(
        {"AAPL": {"Earnings Date": [today], "Earnings Average": [1.5], "Revenue Average": [83e9]}}
    )
    signals = EarningsMonitor(_cfg(), market).check([_FakePosition("AAPL")])
    assert len(signals) == 1
    assert signals[0].severity == "high"
    assert signals[0].data["days_to"] == 0


def test_signal_inside_window():
    in_two_days = date.today() + timedelta(days=2)
    market = _FakeMarket({"AAPL": {"Earnings Date": [in_two_days]}})
    signals = EarningsMonitor(_cfg(days_before=3), market).check([_FakePosition("AAPL")])
    assert len(signals) == 1
    assert signals[0].data["days_to"] == 2


def test_no_signal_when_too_far():
    far = date.today() + timedelta(days=30)
    market = _FakeMarket({"AAPL": {"Earnings Date": [far]}})
    signals = EarningsMonitor(_cfg(days_before=3), market).check([_FakePosition("AAPL")])
    assert signals == []
