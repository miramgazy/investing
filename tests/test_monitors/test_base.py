"""Tests for the Signal dataclass + BaseMonitor."""

from __future__ import annotations

from datetime import datetime

from src.monitors.base import BaseMonitor, Signal


def test_signal_unique_id_is_stable():
    s = Signal(
        signal_type="insider",
        ticker="AAPL",
        severity="high",
        title="t",
        description="d",
        data={"insider": "Tim Cook", "amount": 5_000_000},
        timestamp=datetime(2026, 5, 15, 12, 0, 0),
    )
    a = s.unique_id()
    b = s.unique_id()
    assert a == b
    assert a.startswith("insider_AAPL_2026-05-15_")


def test_signal_unique_id_changes_with_data():
    base_data = {"insider": "Tim Cook"}
    s1 = Signal(
        signal_type="insider", ticker="AAPL", severity="high",
        title="t", description="d", data=base_data,
        timestamp=datetime(2026, 5, 15),
    )
    s2 = Signal(
        signal_type="insider", ticker="AAPL", severity="high",
        title="t", description="d", data={"insider": "Other"},
        timestamp=datetime(2026, 5, 15),
    )
    assert s1.unique_id() != s2.unique_id()


class _DummyConfig:
    class _M:
        insider_trades = True
        analyst_ratings = False
    monitoring = _M()


def test_base_monitor_is_enabled_reads_config_flag():
    class _Insider(BaseMonitor):
        name = "x"
        config_flag = "insider_trades"

        def check(self, positions):
            return []

    class _Analyst(BaseMonitor):
        name = "y"
        config_flag = "analyst_ratings"

        def check(self, positions):
            return []

    cfg = _DummyConfig()
    assert _Insider(cfg).is_enabled() is True
    assert _Analyst(cfg).is_enabled() is False


def test_base_monitor_enabled_when_flag_missing():
    class _M(BaseMonitor):
        name = "m"
        config_flag = "missing_flag"

        def check(self, positions):
            return []

    assert _M(_DummyConfig()).is_enabled() is True
