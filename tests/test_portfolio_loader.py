"""Unit tests for the IBKR portfolio loader."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.portfolio_loader import PortfolioLoader, Position, _merge_positions, _to_float

FIXTURES = Path(__file__).parent / "fixtures"


def _loader_with_file(tmp_path: Path, source: Path, **kwargs) -> PortfolioLoader:
    """Create a fresh portfolio dir with one CSV and instantiate the loader."""
    target = tmp_path / source.name
    shutil.copy(source, target)
    return PortfolioLoader(portfolio_dir=tmp_path, **kwargs)


# ---------- Format-specific parsing ----------


def test_load_activity_statement(tmp_path):
    loader = _loader_with_file(tmp_path, FIXTURES / "ibkr_activity_sample.csv")
    positions = loader.load()

    tickers = [p.ticker for p in positions]
    assert "AAPL" in tickers
    assert "TSLA" in tickers
    # EUR.USD is FX — drop.
    assert "EUR.USD" not in tickers
    # CLOSED has qty=0 — drop.
    assert "CLOSED" not in tickers

    aapl = next(p for p in positions if p.ticker == "AAPL")
    assert aapl.quantity == 100
    assert aapl.average_cost == pytest.approx(150.25)
    assert aapl.market_value == pytest.approx(18050.00)
    assert aapl.currency == "USD"
    assert aapl.unrealized_pnl == pytest.approx(18050.00 - 100 * 150.25)


def test_load_flex_query(tmp_path):
    loader = _loader_with_file(tmp_path, FIXTURES / "ibkr_flex_sample.csv")
    positions = loader.load()

    assert {p.ticker for p in positions} == {
        "AAPL", "TSLA", "NVDA", "MSFT", "META", "SPY",
    }
    aapl = next(p for p in positions if p.ticker == "AAPL")
    assert aapl.market_value == pytest.approx(18050.00)
    assert aapl.asset_type == "STK"


def test_load_simple_csv_dedupes_duplicates(tmp_path):
    loader = _loader_with_file(tmp_path, FIXTURES / "simple_portfolio.csv")
    positions = loader.load()

    aapl = next(p for p in positions if p.ticker == "AAPL")
    # 100 @ 150.25 and 50 @ 160.0 → merged to qty=150 with weighted avg.
    assert aapl.quantity == 150
    expected_avg = (100 * 150.25 + 50 * 160.00) / 150
    assert aapl.average_cost == pytest.approx(expected_avg)


def test_positions_sorted_by_market_value_desc(tmp_path):
    loader = _loader_with_file(tmp_path, FIXTURES / "ibkr_activity_sample.csv")
    positions = loader.load()
    values = [p.market_value for p in positions]
    assert values == sorted(values, reverse=True)


# ---------- Edge cases ----------


def test_fallback_to_config_when_no_csv(tmp_path):
    loader = PortfolioLoader(portfolio_dir=tmp_path, config_tickers=["AAPL", "tsla"])
    positions = loader.load()
    assert [p.ticker for p in positions] == ["AAPL", "TSLA"]
    assert all(p.quantity == 0 for p in positions)


def test_fallback_returns_empty_when_no_csv_and_no_config(tmp_path):
    loader = PortfolioLoader(portfolio_dir=tmp_path)
    assert loader.load() == []


def test_handle_unrecognized_csv(tmp_path):
    """Unrecognized headers fall through to 'simple' parser, return empty."""
    loader = _loader_with_file(tmp_path, FIXTURES / "empty_portfolio.csv")
    positions = loader.load()
    assert positions == []


def test_bom_encoded_csv(tmp_path):
    """CSVs from Excel may begin with a UTF-8 BOM — must read fine."""
    src = (FIXTURES / "simple_portfolio.csv").read_bytes()
    bom_path = tmp_path / "with_bom.csv"
    bom_path.write_bytes(b"\xef\xbb\xbf" + src)
    loader = PortfolioLoader(portfolio_dir=tmp_path)
    positions = loader.load()
    assert any(p.ticker == "AAPL" for p in positions)


# ---------- Helpers ----------


def test_to_float_handles_currency_and_commas():
    assert _to_float("$1,234.56") == pytest.approx(1234.56)
    assert _to_float("—") == 0.0
    assert _to_float(None) == 0.0
    assert _to_float("") == 0.0
    assert _to_float("12.3%") == pytest.approx(12.3)


def test_merge_positions_weighted_average():
    a = Position(ticker="AAPL", quantity=10, average_cost=100, market_value=1100)
    b = Position(ticker="AAPL", quantity=10, average_cost=120, market_value=1300)
    merged = _merge_positions(a, b)
    assert merged.quantity == 20
    assert merged.average_cost == pytest.approx(110)
    assert merged.market_value == pytest.approx(2400)


def test_unrealized_pnl_percent_no_division_by_zero():
    pos = Position(ticker="X", quantity=0, average_cost=0, market_value=100)
    assert pos.unrealized_pnl_percent == 0.0
