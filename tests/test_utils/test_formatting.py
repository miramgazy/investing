"""Formatting helper tests."""

from __future__ import annotations

from src.utils.formatting import (
    escape_html,
    format_currency,
    format_large_number,
    format_percent,
    format_severity_emoji,
    truncate_text,
)


def test_format_currency_basic():
    assert format_currency(1234.5) == "$1,234.50"
    assert format_currency(-89.1, "EUR") == "-€89.10"
    assert format_currency(0) == "$0.00"


def test_format_currency_handles_nan_and_none():
    assert format_currency(None) == "—"
    assert format_currency(float("nan")) == "—"


def test_format_percent_signs():
    assert format_percent(1.234) == "+1.23%"
    assert format_percent(-0.5) == "-0.50%"
    assert format_percent(0) == "0.00%"
    assert format_percent(-0.5, with_sign=False) == "0.50%"


def test_format_large_number_buckets():
    assert format_large_number(1_500_000_000) == "$1.50B"
    assert format_large_number(45_000_000) == "$45.00M"
    assert format_large_number(123_000) == "$123.0K"
    assert format_large_number(999) == "$999.00"  # falls back to currency formatting


def test_escape_html_strips_tags():
    assert escape_html("<script>alert(1)</script>") == "&lt;script&gt;alert(1)&lt;/script&gt;"
    assert escape_html("AT&T") == "AT&amp;T"
    assert escape_html(None) == ""


def test_format_severity_emoji():
    assert format_severity_emoji("low") == "ℹ️"
    assert format_severity_emoji("medium") == "⚠️"
    assert format_severity_emoji("high") == "🚨"
    assert format_severity_emoji("critical") == "🆘"
    assert format_severity_emoji("unknown") == "•"


def test_truncate_text():
    assert truncate_text("hello world", 5) == "hell…"
    assert truncate_text("short", 100) == "short"
    assert truncate_text(None, 10) == ""
