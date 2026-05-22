"""NewsMonitor tests with stubbed market and Claude."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from src.monitors.news import NewsMonitor, _jaccard, _tokenize


def _cfg(min_score: int = 7):
    return SimpleNamespace(
        monitoring=SimpleNamespace(news=True),
        thresholds=SimpleNamespace(news_importance_min=min_score),
    )


@dataclass
class _FakePosition:
    ticker: str


class _FakeMarket:
    def __init__(self, news):
        self.news = news

    def get_recent_news(self, ticker, days=1):
        return self.news.get(ticker, [])


class _FakeClaude:
    def __init__(self, scores):
        # scores: title → (score, reason)
        self.scores = scores
        self.calls = 0

    def score_importance(self, title, ticker):
        self.calls += 1
        return self.scores.get(title, (5, "Routine"))


def test_filters_below_threshold(tmp_path):
    market = _FakeMarket(
        {"AAPL": [{"title": "Apple beats earnings", "publisher": "Bloomberg"}]}
    )
    claude = _FakeClaude({"Apple beats earnings": (6, "Notable but not critical")})
    monitor = NewsMonitor(
        _cfg(min_score=7), market, claude, cache_file=tmp_path / "news_cache.json"
    )
    assert monitor.check([_FakePosition("AAPL")]) == []


def test_emits_signal_above_threshold(tmp_path):
    market = _FakeMarket(
        {"AAPL": [{"title": "Apple recalls all iPhones", "publisher": "Bloomberg"}]}
    )
    claude = _FakeClaude(
        {"Apple recalls all iPhones": (9, "Material recall — high importance")}
    )
    monitor = NewsMonitor(
        _cfg(min_score=7), market, claude, cache_file=tmp_path / "news_cache.json"
    )
    signals = monitor.check([_FakePosition("AAPL")])
    assert len(signals) == 1
    sig = signals[0]
    assert sig.severity == "high"
    assert sig.ticker == "AAPL"
    assert sig.data["score"] == 9


def test_cache_avoids_repeated_claude_calls(tmp_path):
    cache_path = tmp_path / "news_cache.json"
    market = _FakeMarket(
        {"AAPL": [{"title": "Apple recalls all iPhones", "publisher": "Bloomberg"}]}
    )
    claude = _FakeClaude(
        {"Apple recalls all iPhones": (9, "Material recall — high importance")}
    )

    NewsMonitor(_cfg(min_score=7), market, claude, cache_file=cache_path).check(
        [_FakePosition("AAPL")]
    )
    assert claude.calls == 1

    # Second run — pulls from cache, no new Claude call.
    NewsMonitor(_cfg(min_score=7), market, claude, cache_file=cache_path).check(
        [_FakePosition("AAPL")]
    )
    assert claude.calls == 1
    assert json.loads(Path(cache_path).read_text())


def test_dedup_drops_near_duplicate_titles(tmp_path):
    market = _FakeMarket(
        {
            "AAPL": [
                {"title": "Apple recalls iPhone 17 due to safety risks", "publisher": "X"},
                {"title": "Apple recalls iPhone 17 over safety risks", "publisher": "Y"},
            ]
        }
    )
    claude = _FakeClaude(
        {
            "Apple recalls iPhone 17 due to safety risks": (9, "high"),
            "Apple recalls iPhone 17 over safety risks": (9, "high"),
        }
    )
    monitor = NewsMonitor(
        _cfg(min_score=7), market, claude, cache_file=tmp_path / "news.json"
    )
    signals = monitor.check([_FakePosition("AAPL")])
    assert len(signals) == 1


def test_jaccard_basic():
    a = _tokenize("Apple recalls iPhones")
    b = _tokenize("Apple recalls iPhone units")
    assert _jaccard(a, b) > 0.3
    assert _jaccard(set(), a) == 0.0
