"""ClaudeClient tests — anthropic SDK is mocked, no network."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.clients.claude import ClaudeClient, ClaudeError, _parse_score_json


def _make_response(text: str):
    block = SimpleNamespace(type="text", text=text)
    return SimpleNamespace(
        content=[block],
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
    )


def test_init_requires_api_key():
    with pytest.raises(ClaudeError):
        ClaudeClient("")


def test_analyze_returns_text():
    client = ClaudeClient("sk-x")
    client._client = MagicMock()
    client._client.messages.create.return_value = _make_response("Hello!")
    assert client.analyze("hi") == "Hello!"


def test_score_importance_extracts_score_and_reason():
    client = ClaudeClient("sk-x")
    client._client = MagicMock()
    client._client.messages.create.return_value = _make_response(
        '{"score": 8, "reason": "Регуляторное расследование"}'
    )
    score, reason = client.score_importance("Apple faces EU probe", "AAPL")
    assert score == 8
    assert "Регуляторное" in reason


def test_score_importance_handles_malformed_json():
    client = ClaudeClient("sk-x")
    client._client = MagicMock()
    client._client.messages.create.return_value = _make_response("blah blah no json")
    score, _ = client.score_importance("x", "AAPL")
    assert 1 <= score <= 10


def test_parse_score_json_clamps_score():
    assert _parse_score_json('{"score": 99, "reason": "y"}')[0] == 10
    assert _parse_score_json('{"score": -3, "reason": "y"}')[0] == 1
    # Score wrapped in ```json fences.
    score, _ = _parse_score_json('```json\n{"score": 7, "reason": "y"}\n```')
    assert score == 7
