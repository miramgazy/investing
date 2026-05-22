"""Config loader tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import ConfigError, load_config


def _write_minimal_config(path: Path, **overrides) -> Path:
    content = """\
tickers: [AAPL, MSFT]

monitoring:
  insider_trades: true
  analyst_ratings: true
  price_movements: true
  news: true
  earnings: true
  macro: true
  volatility: true

thresholds:
  price_movement_percent: 3.0
  news_importance_min: 7
  insider_min_value_usd: 1000000
  vix_alert_level: 25.0
  earnings_days_before: 3

reports:
  language: ru
  timezone: Europe/Moscow
  currency: USD
  benchmark: SPY

claude:
  model: claude-sonnet-4-20250514
  insights_style: professional

pdf:
  theme: dark
  accent_color: "#00d4ff"
"""
    path.write_text(content, encoding="utf-8")
    return path


def _set_secrets(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "abc:def")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setenv("CLAUDE_API_KEY", "sk-test")


def test_load_config_happy_path(tmp_path, monkeypatch):
    path = _write_minimal_config(tmp_path / "config.yaml")
    _set_secrets(monkeypatch)
    cfg = load_config(path)
    assert cfg.tickers == ["AAPL", "MSFT"]
    assert cfg.thresholds.price_movement_percent == 3.0
    assert cfg.monitoring.enabled_count() == 7
    assert cfg.has_secrets() is True


def test_missing_secrets_raises(tmp_path, monkeypatch):
    path = _write_minimal_config(tmp_path / "config.yaml")
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    monkeypatch.delenv("CLAUDE_API_KEY", raising=False)
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "TELEGRAM_BOT_TOKEN" in str(exc.value)


def test_invalid_value_raises_with_field_name(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(
        """\
tickers: []
monitoring: {insider_trades: true, analyst_ratings: true, price_movements: true,
             news: true, earnings: true, macro: true, volatility: true}
thresholds:
  price_movement_percent: 99.0   # > 20 → must reject
  news_importance_min: 7
  insider_min_value_usd: 1000000
  vix_alert_level: 25.0
  earnings_days_before: 3
""",
        encoding="utf-8",
    )
    _set_secrets(monkeypatch)
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "price_movement_percent" in str(exc.value)


def test_missing_file_raises(monkeypatch, tmp_path):
    _set_secrets(monkeypatch)
    missing = tmp_path / "nope.yaml"
    with pytest.raises(ConfigError) as exc:
        load_config(missing)
    assert "config" in str(exc.value).lower()


def test_invalid_hex_accent_rejected(tmp_path, monkeypatch):
    path = _write_minimal_config(tmp_path / "c.yaml")
    # Append a bogus pdf section.
    text = path.read_text(encoding="utf-8")
    text = text.replace('accent_color: "#00d4ff"', 'accent_color: "not-hex"')
    path.write_text(text, encoding="utf-8")
    _set_secrets(monkeypatch)
    with pytest.raises(ConfigError) as exc:
        load_config(path)
    assert "accent_color" in str(exc.value)
