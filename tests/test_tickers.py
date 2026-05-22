"""Unit tests for TickerUtils — uses a hand-crafted cache file (no network)."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from src.utils.tickers import TickerUtils


@pytest.fixture
def cache_file(tmp_path: Path) -> Path:
    """Pre-populated CIK cache; lets us bypass the SEC HTTP request."""
    cache = tmp_path / "cik_cache.json"
    cache.write_text(
        json.dumps(
            {
                "AAPL": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."},
                "TSLA": {"cik_str": 1318605, "ticker": "TSLA", "title": "Tesla, Inc."},
            }
        ),
        encoding="utf-8",
    )
    # Ensure the cache is considered fresh.
    now = time.time()
    import os

    os.utime(cache, (now, now))
    return cache


def test_get_cik_known_ticker(cache_file):
    tickers = TickerUtils(cache_file=cache_file)
    assert tickers.get_cik("AAPL") == "0000320193"
    assert tickers.get_cik("aapl") == "0000320193"  # case-insensitive


def test_get_cik_unknown_ticker(cache_file):
    tickers = TickerUtils(cache_file=cache_file)
    assert tickers.get_cik("XYZINVALID") is None
    assert tickers.get_cik("") is None


def test_get_company_name(cache_file):
    tickers = TickerUtils(cache_file=cache_file)
    assert tickers.get_company_name("AAPL") == "Apple Inc."
    assert tickers.get_company_name("XYZ") == ""


def test_validate_ticker(cache_file):
    tickers = TickerUtils(cache_file=cache_file)
    assert tickers.validate_ticker("TSLA")
    assert not tickers.validate_ticker("BOGUS")


def test_cache_stale_triggers_refresh(tmp_path, monkeypatch):
    """When the cache file is older than 7 days, we go back to the network."""
    cache = tmp_path / "cik_cache.json"
    cache.write_text(json.dumps({"OLD": {"cik_str": 1, "ticker": "OLD", "title": "Old"}}))
    # Mark file as 8 days old.
    eight_days_ago = time.time() - 8 * 86400
    import os

    os.utime(cache, (eight_days_ago, eight_days_ago))

    def fake_refresh(self):
        return {"NEW": {"cik_str": 2, "ticker": "NEW", "title": "New Co."}}

    monkeypatch.setattr(TickerUtils, "_refresh_cache", fake_refresh)

    tickers = TickerUtils(cache_file=cache)
    # Old data should be gone, new data should be present.
    assert tickers.get_cik("NEW") == "0000000002"
    assert tickers.get_cik("OLD") is None
