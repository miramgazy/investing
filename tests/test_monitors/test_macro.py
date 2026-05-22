"""MacroMonitor tests — purely deterministic, no I/O."""

from __future__ import annotations

from datetime import date, timedelta

from src.monitors.macro import _nth_weekday, _upcoming_events


def test_nth_weekday_known_dates():
    # First Friday of January 2026 = 2 Jan.
    assert _nth_weekday(2026, 1, weekday=4, n=1) == date(2026, 1, 2)
    # Second Tuesday of May 2026 = 12 May.
    assert _nth_weekday(2026, 5, weekday=1, n=2) == date(2026, 5, 12)


def test_upcoming_events_within_window():
    today = date(2026, 5, 10)  # Sunday
    events = _upcoming_events(today, window_days=7)
    # Should include 2nd Tuesday of May 2026 (CPI on May 12).
    assert any(e["date"] == date(2026, 5, 12) for e in events)
    # All events must be inside the window.
    for e in events:
        assert today <= e["date"] <= today + timedelta(days=7)
