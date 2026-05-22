"""InsiderMonitor tests with stubbed SEC client + ticker utils."""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from src.monitors.insider import InsiderMonitor, _severity_for_amount


def _cfg(min_value: int = 1_000_000):
    return SimpleNamespace(
        monitoring=SimpleNamespace(insider_trades=True),
        thresholds=SimpleNamespace(insider_min_value_usd=min_value),
    )


@dataclass
class _FakePosition:
    ticker: str


class _FakeTickers:
    def __init__(self, mapping):
        self.mapping = mapping

    def get_cik(self, ticker):
        return self.mapping.get(ticker)


class _FakeSEC:
    """Returns canned recent filings + details by accession number."""

    def __init__(self, recent: dict[str, list[dict]], details: dict[str, dict]):
        # recent: key = (cik, days) → list of filings
        self.recent = recent
        self.details = details

    def get_recent_filings(self, cik, form_type="4", days=1):
        return self.recent.get((cik, days), [])

    def get_form4_details(self, cik, accession):
        return self.details.get(accession, {})

    def get_company_filings_url(self, cik):
        return f"https://example/{cik}"


def test_severity_buckets():
    assert _severity_for_amount(500_000) == "medium"
    assert _severity_for_amount(15_000_000) == "high"
    assert _severity_for_amount(75_000_000) == "critical"


def test_single_sale_above_threshold_generates_signal():
    sec = _FakeSEC(
        recent={
            ("0000320193", 1): [{"accession_number": "ACC-1", "filed_at": "2026-05-15"}],
            ("0000320193", 30): [{"accession_number": "ACC-1", "filed_at": "2026-05-15"}],
        },
        details={
            "ACC-1": {
                "insider_name": "Tim Cook",
                "insider_title": "CEO",
                "transaction_type": "S",
                "shares": 50_000,
                "price_per_share": 200.0,
                "total_value": 10_000_000.0,
            },
        },
    )
    tickers = _FakeTickers({"AAPL": "0000320193"})
    monitor = InsiderMonitor(_cfg(min_value=1_000_000), sec, tickers)
    signals = monitor.check([_FakePosition("AAPL")])

    insider_signals = [s for s in signals if not s.data.get("cluster")]
    assert len(insider_signals) == 1
    assert insider_signals[0].ticker == "AAPL"
    assert insider_signals[0].severity == "high"  # $10M sale
    assert insider_signals[0].data["insider_name"] == "Tim Cook"


def test_cluster_signal_when_three_plus_insiders_sell():
    sec = _FakeSEC(
        recent={
            ("0000320193", 1): [],
            ("0000320193", 30): [
                {"accession_number": f"ACC-{i}", "filed_at": "2026-05-10"}
                for i in range(4)
            ],
        },
        details={
            f"ACC-{i}": {
                "insider_name": f"Insider {i}",
                "insider_title": "Director",
                "transaction_type": "S",
                "shares": 10_000,
                "price_per_share": 200.0,
                "total_value": 2_000_000.0,
            }
            for i in range(4)
        },
    )
    tickers = _FakeTickers({"AAPL": "0000320193"})
    monitor = InsiderMonitor(_cfg(min_value=1_000_000), sec, tickers)
    signals = monitor.check([_FakePosition("AAPL")])

    cluster = [s for s in signals if s.data.get("cluster")]
    assert len(cluster) == 1
    assert cluster[0].severity == "critical"
    assert cluster[0].data["insiders_count"] == 4
    assert cluster[0].data["total_value"] == 8_000_000


def test_skips_non_sale_transactions():
    sec = _FakeSEC(
        recent={
            ("0000320193", 1): [{"accession_number": "ACC-1", "filed_at": "2026-05-15"}],
            ("0000320193", 30): [],
        },
        details={
            "ACC-1": {
                "insider_name": "Tim Cook",
                "insider_title": "CEO",
                "transaction_type": "P",  # purchase, not sale
                "shares": 50_000,
                "price_per_share": 200.0,
                "total_value": 10_000_000.0,
            },
        },
    )
    tickers = _FakeTickers({"AAPL": "0000320193"})
    monitor = InsiderMonitor(_cfg(), sec, tickers)
    assert monitor.check([_FakePosition("AAPL")]) == []


def test_missing_cik_is_silently_skipped():
    sec = _FakeSEC(recent={}, details={})
    tickers = _FakeTickers({})  # no CIK known
    monitor = InsiderMonitor(_cfg(), sec, tickers)
    assert monitor.check([_FakePosition("UNKNOWN")]) == []
