"""Telegram Bot API client.

Особенности:

- Принудительный UTF-8 (важно для кириллицы и эмодзи).
- ``tenacity``-retry с экспоненциальным backoff'ом на сетевые сбои и 5xx.
- Уважение ``Retry-After`` при ``HTTP 429`` (rate limit).
- Автоматическое разбиение сообщений длиннее 4096 символов.
- Никакого ``python-telegram-bot`` — только ``requests``.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Final

import requests
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.constants import TELEGRAM_MAX_MESSAGE_LENGTH, TELEGRAM_SAFE_MESSAGE_LENGTH
from src.utils.logger import get_logger

_API_BASE: Final = "https://api.telegram.org/bot{token}/{method}"
_REQUEST_TIMEOUT: Final = 30


class TelegramError(RuntimeError):
    """Telegram API returned an error response."""


class TelegramClient:
    """Thin wrapper around the Telegram Bot HTTP API."""

    def __init__(self, bot_token: str, chat_id: str | int) -> None:
        if not bot_token or not chat_id:
            raise TelegramError("Empty bot_token or chat_id")
        self._token = bot_token
        self._chat_id = str(chat_id)
        self._session = requests.Session()
        self._logger = get_logger("telegram")

    # ---------- Public API ----------

    def send_message(
        self,
        text: str,
        parse_mode: str = "HTML",
        disable_preview: bool = True,
    ) -> bool:
        """Send a text message, splitting if it overflows Telegram's 4096-char cap."""
        if not text:
            return False

        # Telegram cap is 4096 — use a safer 3900 to leave room for HTML tags
        # that we cannot accurately measure as bytes upfront.
        chunks = _split_message(text, TELEGRAM_SAFE_MESSAGE_LENGTH)
        ok = True
        for chunk in chunks:
            ok = self._send_message_chunk(chunk, parse_mode, disable_preview) and ok
        return ok

    def send_document(self, file_path: str | Path, caption: str = "") -> bool:
        """Upload a local file (PDF, image, ...) with optional caption."""
        path = Path(file_path)
        if not path.exists():
            self._logger.error("Document not found: %s", path)
            return False

        try:
            return self._send_document_inner(path, caption)
        except RetryError as exc:
            self._logger.error("send_document failed after retries: %s", exc)
            return False

    def send_photo(self, file_path: str | Path, caption: str = "") -> bool:
        """Send a local image as a photo (auto-compressed by Telegram)."""
        path = Path(file_path)
        if not path.exists():
            self._logger.error("Photo not found: %s", path)
            return False
        try:
            return self._send_photo_inner(path, caption)
        except RetryError as exc:
            self._logger.error("send_photo failed after retries: %s", exc)
            return False

    def send_error(self, error_text: str) -> bool:
        """Send a simplified error notification, no parse_mode (avoid escape pain)."""
        text = f"⚠️ {error_text}" if not error_text.startswith(("⚠️", "🔥")) else error_text
        return self._send_message_chunk(text, parse_mode=None, disable_preview=True)

    # ---------- Internals ----------

    def _send_message_chunk(
        self,
        text: str,
        parse_mode: str | None,
        disable_preview: bool,
    ) -> bool:
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
        }
        if parse_mode:
            payload["parse_mode"] = parse_mode

        try:
            self._post("sendMessage", json_payload=payload)
            self._logger.info("Message sent (%d chars)", len(text))
            return True
        except RetryError as exc:
            self._logger.error("send_message failed after retries: %s", exc)
            return False
        except TelegramError as exc:
            self._logger.error("send_message Telegram error: %s", exc)
            return False

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _send_document_inner(self, path: Path, caption: str) -> bool:
        with path.open("rb") as fh:
            files = {"document": (path.name, fh)}
            data = {"chat_id": self._chat_id}
            if caption:
                data["caption"] = caption
                data["parse_mode"] = "HTML"
            self._post("sendDocument", data=data, files=files)
        self._logger.info("Document sent: %s", path.name)
        return True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _send_photo_inner(self, path: Path, caption: str) -> bool:
        with path.open("rb") as fh:
            files = {"photo": (path.name, fh)}
            data = {"chat_id": self._chat_id}
            if caption:
                data["caption"] = caption
                data["parse_mode"] = "HTML"
            self._post("sendPhoto", data=data, files=files)
        self._logger.info("Photo sent: %s", path.name)
        return True

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((requests.RequestException,)),
        reraise=True,
    )
    def _post(
        self,
        method: str,
        json_payload: dict | None = None,
        data: dict | None = None,
        files: dict | None = None,
    ) -> dict:
        url = _API_BASE.format(token=self._token, method=method)
        # UTF-8 явно прописываем в заголовке — иногда сервера/прокси
        # пытаются угадать кодировку и портят кириллицу.
        headers = {"Accept-Charset": "utf-8"}
        if json_payload is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
            response = self._session.post(
                url, json=json_payload, headers=headers, timeout=_REQUEST_TIMEOUT
            )
        else:
            response = self._session.post(
                url, data=data, files=files, headers=headers, timeout=_REQUEST_TIMEOUT
            )

        # Rate limiting — Telegram возвращает Retry-After в секундах.
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", "1"))
            self._logger.warning("Telegram rate limit, sleeping %ds", retry_after)
            time.sleep(retry_after)
            # Re-raise as a requests-style error so tenacity повторит запрос.
            raise requests.HTTPError("429 Too Many Requests", response=response)

        if response.status_code >= 500:
            raise requests.HTTPError(
                f"{response.status_code} server error", response=response
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise TelegramError(f"Non-JSON response: {response.text[:200]}") from exc

        if not payload.get("ok", False):
            description = payload.get("description", "unknown error")
            error_code = payload.get("error_code")
            raise TelegramError(f"[{error_code}] {description}")

        return payload


# ---------- Helpers ----------


def _split_message(text: str, limit: int) -> list[str]:
    """Split a long message on newline boundaries, never exceeding ``limit``."""
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in text.splitlines(keepends=True):
        if len(line) > limit:
            # Single huge line — hard-split it.
            if current:
                parts.append("".join(current))
                current = []
                current_len = 0
            for i in range(0, len(line), limit):
                parts.append(line[i : i + limit])
            continue

        if current_len + len(line) > limit:
            parts.append("".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len += len(line)

    if current:
        parts.append("".join(current))

    # Final safety net.
    return [p[:TELEGRAM_MAX_MESSAGE_LENGTH] for p in parts]
