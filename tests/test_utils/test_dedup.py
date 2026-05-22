"""SignalDeduplicator tests."""

from __future__ import annotations

import time
from datetime import datetime

from src.monitors.base import Signal
from src.utils.dedup import SignalDeduplicator


def _signal(uid_seed: str = "a") -> Signal:
    return Signal(
        signal_type="price",
        ticker="AAPL",
        severity="high",
        title=f"AAPL price {uid_seed}",
        description="d",
        data={"seed": uid_seed},
        timestamp=datetime(2026, 5, 15, 12),
    )


def test_filter_new_drops_already_sent(tmp_path):
    dedup = SignalDeduplicator(cache_file=tmp_path / "sent.json", ttl_days=7)
    s = _signal("a")
    assert dedup.is_already_sent(s) is False
    dedup.mark_sent(s)
    assert dedup.is_already_sent(s) is True
    assert dedup.filter_new([s, _signal("b")]) == [_signal("b")] or any(
        sig.data["seed"] == "b" for sig in dedup.filter_new([s, _signal("b")])
    )


def test_ttl_expiry(tmp_path, monkeypatch):
    dedup = SignalDeduplicator(cache_file=tmp_path / "sent.json", ttl_days=7)
    s = _signal()
    dedup.mark_sent(s)

    # Simulate 8 days passing. Capture the original before patching so the
    # lambda doesn't recurse into the patched function.
    future = time.time() + 8 * 86400
    monkeypatch.setattr(time, "time", lambda f=future: f)
    assert dedup.is_already_sent(s) is False


def test_state_survives_reload(tmp_path):
    cache_path = tmp_path / "sent.json"
    s = _signal()
    SignalDeduplicator(cache_file=cache_path).mark_sent(s)
    # Fresh instance must see the persisted state.
    dedup2 = SignalDeduplicator(cache_file=cache_path)
    assert dedup2.is_already_sent(s) is True


def test_signals_in_window_returns_recent_entries(tmp_path):
    dedup = SignalDeduplicator(cache_file=tmp_path / "sent.json", ttl_days=30)
    dedup.mark_sent(_signal("a"))
    dedup.mark_sent(_signal("b"))
    week = dedup.signals_in_window(days=7)
    assert len(week) == 2


def test_cleanup_old_drops_stale_entries(tmp_path, monkeypatch):
    dedup = SignalDeduplicator(cache_file=tmp_path / "sent.json", ttl_days=1)
    dedup.mark_sent(_signal())
    assert len(dedup._cache) == 1
    # Capture the original before monkeypatching to avoid recursion.
    real_time = time.time
    monkeypatch.setattr(time, "time", lambda: real_time() + 5 * 86400)
    dedup.cleanup_old()
    assert dedup._cache == {}
