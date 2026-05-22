"""Smoke test that the weekly PDF really renders without crashes.

This test caught two production bugs during development:
    1. ``HexColor.hexval()`` returns ``"0xRRGGBB"`` but matplotlib needs
       ``"#RRGGBB"`` — without the fix the chart subsystem raised
       ``ValueError: Key axes.facecolor: '0x1a1f3a' does not look like
       a color arg`` and no PDF was produced.
    2. ReportLab's Helvetica has no Cyrillic glyphs — every Russian
       sentence rendered as ▢▢▢. We register ``DejaVu Sans`` shipped
       with matplotlib; this test ensures fonts stay registered.

The test stubs both Claude and the market client so it is fast and
deterministic — no network, no random failures.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.reports.weekly_pdf import WeeklyReport


@dataclass
class _Pos:
    ticker: str
    quantity: float
    average_cost: float
    market_value: float
    sector: str = "Technology"
    company_name: str = ""

    @property
    def total_cost(self) -> float:
        return self.quantity * self.average_cost


class _FakeMarket:
    def __init__(self, seed: int = 42) -> None:
        self._rng = np.random.default_rng(seed)

    def _history(self, ticker: str, days: int):
        # Deterministic per-ticker drift so charts look real.
        drift = {"AAPL": 0.001, "TSLA": -0.0015, "NVDA": 0.003,
                 "MSFT": 0.0008, "SPY": 0.0005, "QQQ": 0.0007,
                 "^VIX": 0.0}.get(ticker, 0.0005)
        noise = self._rng.normal(drift, 0.015, days)
        prices = 100 * (1 + noise).cumprod()
        idx = pd.date_range(end=datetime.now().date(), periods=days, freq="D")
        return pd.DataFrame({"Close": prices}, index=idx)

    def get_price_history(self, ticker, period="1mo", interval="1d"):
        days = {"5d": 7, "1mo": 30, "3mo": 90, "1y": 250, "1w": 10}.get(period, 30)
        return self._history(ticker, days)

    def get_current_price(self, ticker):
        return float(self._history(ticker, 5)["Close"].iloc[-1])

    def get_company_info(self, ticker):
        return {"sector": "Technology", "long_name": f"{ticker} Inc."}

    def get_recent_news(self, ticker, days=1):
        return []

    def get_recommendations(self, ticker):
        return pd.DataFrame()

    def get_earnings_calendar(self, ticker):
        return {"Earnings Date": [datetime.now().date() + timedelta(days=5)]}

    def batch_get_prices(self, tickers):
        return {t: self.get_current_price(t) for t in tickers}


class _FakeClaude:
    def analyze(self, prompt, system=None, max_tokens=1024, temperature=0.2):
        return "Синтетический комментарий Claude для теста."

    def score_importance(self, news, ticker):
        return 5, "Нейтрально"

    def generate_insights(self, *a, **k):
        return "Синтетические insights с кириллицей."

    def generate_summary(self, *a, **k):
        return "Краткое резюме."


@pytest.fixture
def fake_config():
    return SimpleNamespace(
        reports=SimpleNamespace(currency="USD", benchmark="SPY",
                                language="ru", timezone="Europe/Moscow"),
        pdf=SimpleNamespace(theme="dark", accent_color="#00d4ff"),
        claude=SimpleNamespace(model="claude-sonnet-4-20250514",
                               insights_style="professional"),
        thresholds=SimpleNamespace(price_movement_percent=3.0,
                                   news_importance_min=7,
                                   insider_min_value_usd=1_000_000,
                                   vix_alert_level=25.0,
                                   earnings_days_before=3),
        monitoring=SimpleNamespace(insider_trades=True, analyst_ratings=True,
                                   price_movements=True, news=True, earnings=True,
                                   macro=True, volatility=True),
        tickers=["AAPL", "MSFT", "TSLA"],
    )


@pytest.fixture
def positions():
    return [
        _Pos("AAPL", 100, 150, 18000, sector="Technology", company_name="Apple Inc."),
        _Pos("MSFT", 40, 300, 14000, sector="Technology", company_name="Microsoft"),
        _Pos("TSLA", 50, 250, 10000, sector="Consumer Discretionary", company_name="Tesla"),
    ]


def test_weekly_pdf_generates_for_dark_theme(tmp_path, monkeypatch, fake_config, positions):
    monkeypatch.chdir(tmp_path)
    Path("data/reports_archive").mkdir(parents=True, exist_ok=True)

    pdf_path = WeeklyReport(
        config=fake_config,
        market_client=_FakeMarket(),
        claude_client=_FakeClaude(),
        deduplicator=None,
    ).generate(positions)

    assert Path(pdf_path).exists()
    size = Path(pdf_path).stat().st_size
    # Anything below 50 KB means a section silently produced an empty page.
    assert size > 50_000, f"PDF suspiciously small: {size} bytes"


def test_weekly_pdf_generates_for_light_theme(tmp_path, monkeypatch, fake_config, positions):
    monkeypatch.chdir(tmp_path)
    Path("data/reports_archive").mkdir(parents=True, exist_ok=True)
    fake_config.pdf = SimpleNamespace(theme="light", accent_color="#2563eb")

    pdf_path = WeeklyReport(
        config=fake_config,
        market_client=_FakeMarket(seed=99),
        claude_client=_FakeClaude(),
        deduplicator=None,
    ).generate(positions)

    assert Path(pdf_path).exists()
    assert Path(pdf_path).stat().st_size > 50_000


def test_chart_colors_normalized_for_matplotlib():
    """Regression test for the HexColor → matplotlib '0x' vs '#' bug."""
    from src.reports.charts import _hex
    from src.reports.pdf_templates import PDFTheme

    theme = PDFTheme(theme="dark")
    result = _hex(theme.bg_secondary)
    assert result.startswith("#"), f"Expected #-prefixed hex, got {result!r}"
    assert len(result) == 7


def test_font_registration_is_idempotent():
    """Calling _register_fonts() twice must not blow up."""
    from src.reports.pdf_templates import _register_fonts

    _register_fonts()
    _register_fonts()  # second call should be a no-op
