"""TelegramClient tests — fully mocked, no network."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.clients.telegram import TelegramClient, TelegramError, _split_message


@pytest.fixture
def fake_session(monkeypatch):
    sess = MagicMock()
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = {"ok": True, "result": {}}
    response.headers = {}
    sess.post.return_value = response
    return sess


def test_init_validates_inputs():
    with pytest.raises(TelegramError):
        TelegramClient("", "1")
    with pytest.raises(TelegramError):
        TelegramClient("token", "")


def test_send_message_happy_path(fake_session):
    client = TelegramClient("token", "42")
    client._session = fake_session
    assert client.send_message("hello") is True
    fake_session.post.assert_called_once()
    args, kwargs = fake_session.post.call_args
    assert "sendMessage" in args[0]
    payload = kwargs["json"]
    assert payload["chat_id"] == "42"
    assert payload["text"] == "hello"
    assert payload["parse_mode"] == "HTML"


def test_send_message_handles_4xx(fake_session):
    fake_session.post.return_value.status_code = 200
    fake_session.post.return_value.json.return_value = {
        "ok": False, "error_code": 400, "description": "chat not found"
    }
    client = TelegramClient("token", "42")
    client._session = fake_session
    assert client.send_message("hi") is False


def test_split_message_breaks_on_newlines():
    text = "line1\n" * 1000  # ~6000 chars
    parts = _split_message(text, limit=2000)
    assert all(len(p) <= 2000 for p in parts)
    assert "".join(parts) == text


def test_split_message_handles_huge_line():
    text = "x" * 5000
    parts = _split_message(text, limit=2000)
    assert all(len(p) <= 2000 for p in parts)
    assert "".join(parts) == text


def test_send_error_does_not_use_html_parse_mode(fake_session):
    client = TelegramClient("token", "42")
    client._session = fake_session
    assert client.send_error("Something broke") is True
    payload = fake_session.post.call_args[1]["json"]
    assert "parse_mode" not in payload  # plain text → no HTML escaping pain
    assert payload["text"].startswith("⚠️")


def test_send_document_missing_file_returns_false(tmp_path):
    client = TelegramClient("token", "42")
    assert client.send_document(tmp_path / "nope.pdf", "caption") is False
