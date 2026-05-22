"""Snapshot-style tests for the Telegram HTML templates."""

from __future__ import annotations

from datetime import datetime

from src.monitors.base import Signal
from src.utils.templates import format_signal


def _make(signal_type, **overrides):
    base = dict(
        signal_type=signal_type,
        ticker="AAPL",
        severity="high",
        title="t",
        description="d",
        data={},
        timestamp=datetime(2026, 5, 15, 12),
        source_url="",
    )
    base.update(overrides)
    return Signal(**base)


def test_insider_renders_named_fields():
    s = _make("insider", data={
        "insider_name": "Tim Cook",
        "insider_title": "CEO",
        "total_value": 12_000_000,
        "shares": 50_000,
        "filed_at": "2026-05-14",
    })
    out = format_signal(s)
    assert "Tim Cook" in out
    assert "CEO" in out
    assert "$12.00M" in out
    assert "Form 4" in out


def test_cluster_renders_list():
    s = _make("insider", severity="critical", data={
        "cluster": True,
        "insiders_count": 3,
        "total_value": 50_000_000,
        "window_days": 30,
        "by_insider": [("Robyn Denholm", 30_000_000), ("Elon Musk", 20_000_000)],
    })
    out = format_signal(s)
    assert "Кластер инсайдерских продаж" in out
    assert "Robyn Denholm" in out
    assert "Elon Musk" in out


def test_price_renders_relative_strength():
    s = _make("price", severity="high", data={
        "change_percent": -7.2,
        "benchmark": "SPY",
        "benchmark_change_percent": -0.4,
        "relative_strength": -6.8,
    })
    out = format_signal(s)
    assert "-7.20%" in out
    assert "-6.80%" in out
    assert "SPY" in out


def test_news_renders_score():
    s = _make("news", data={
        "publisher": "Bloomberg",
        "title": "Apple beats earnings",
        "score": 9,
        "reason": "Существенно для бизнеса",
    })
    out = format_signal(s)
    assert "Bloomberg" in out
    assert "9/10" in out


def test_html_escape_prevents_tag_injection():
    s = _make("news", data={
        "publisher": "X",
        "title": "<script>alert(1)</script>",
        "score": 8,
        "reason": "h",
    })
    out = format_signal(s)
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_source_url_appended_when_present():
    s = _make("insider", source_url="https://example.com", data={
        "insider_name": "x", "insider_title": "y", "total_value": 5e6,
        "shares": 1, "filed_at": "2026-05-15",
    })
    out = format_signal(s)
    assert "example.com" in out
