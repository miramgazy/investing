"""Shared pytest fixtures."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


@pytest.fixture
def mini_config():
    """Lightweight stand-in for the pydantic Config used by monitors."""
    return SimpleNamespace(
        monitoring=SimpleNamespace(
            insider_trades=True,
            analyst_ratings=True,
            price_movements=True,
            news=True,
            earnings=True,
            macro=True,
            volatility=True,
        ),
        thresholds=SimpleNamespace(
            price_movement_percent=3.0,
            news_importance_min=7,
            insider_min_value_usd=1_000_000,
            vix_alert_level=25.0,
            earnings_days_before=3,
        ),
        reports=SimpleNamespace(
            language="ru",
            timezone="Europe/Moscow",
            currency="USD",
            benchmark="SPY",
        ),
        claude=SimpleNamespace(
            model="claude-sonnet-4-20250514",
            insights_style="professional",
        ),
        pdf=SimpleNamespace(theme="dark", accent_color="#00d4ff"),
        tickers=["AAPL", "TSLA"],
        telegram_bot_token="x",
        telegram_chat_id="1",
        claude_api_key="sk-test",
    )
