"""AnalystMonitor tests using stubbed yfinance-style frame."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from types import SimpleNamespace

import pandas as pd

from src.monitors.analysts import AnalystMonitor, _is_major_bank


def _cfg():
    return SimpleNamespace(monitoring=SimpleNamespace(analyst_ratings=True))


@dataclass
class _FakePosition:
    ticker: str


class _FakeMarket:
    def __init__(self, df: pd.DataFrame):
        self.df = df

    def get_recommendations(self, ticker):
        return self.df


def _now_index(n: int = 1):
    return pd.DatetimeIndex([datetime.now() - timedelta(hours=h) for h in range(n)])


def test_major_bank_detection():
    assert _is_major_bank("Goldman Sachs")
    assert _is_major_bank("JPMorgan Chase")
    assert not _is_major_bank("Pets.com Research")


def test_downgrade_from_major_bank_creates_high_signal():
    df = pd.DataFrame(
        {
            "Firm": ["Goldman Sachs"],
            "From Grade": ["Buy"],
            "To Grade": ["Sell"],
            "Action": ["down"],
        },
        index=_now_index(1),
    )
    monitor = AnalystMonitor(_cfg(), _FakeMarket(df))
    signals = monitor.check([_FakePosition("AAPL")])
    assert len(signals) == 1
    assert signals[0].severity == "high"
    assert signals[0].data["direction"] == "downgrade"


def test_non_major_bank_is_ignored():
    df = pd.DataFrame(
        {
            "Firm": ["Tiny Research LLC"],
            "From Grade": ["Buy"],
            "To Grade": ["Sell"],
            "Action": ["down"],
        },
        index=_now_index(1),
    )
    monitor = AnalystMonitor(_cfg(), _FakeMarket(df))
    assert monitor.check([_FakePosition("AAPL")]) == []


def test_initiate_buy_from_major():
    df = pd.DataFrame(
        {
            "Firm": ["Morgan Stanley"],
            "From Grade": [""],
            "To Grade": ["Overweight"],
            "Action": ["init"],
        },
        index=_now_index(1),
    )
    monitor = AnalystMonitor(_cfg(), _FakeMarket(df))
    signals = monitor.check([_FakePosition("AAPL")])
    assert len(signals) == 1
    assert signals[0].data["direction"] == "initiated_buy"
