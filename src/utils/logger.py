"""Structured logger.

Формат: ``[LEVEL] timestamp module: message``.
Уровень: ``INFO`` по умолчанию, ``DEBUG`` если задана env-переменная
``WATCHDOG_DEBUG=1``. Все логгеры — потомки одного root, чтобы можно было
менять уровень в одном месте.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys

_ROOT_NAME = "watchdog"
_CONFIGURED = False


def _configure_root() -> None:
    """Configure root handler exactly once."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    # Force UTF-8 on stdout/stderr — иначе на Windows консоль cp1251 падает
    # на любом эмодзи или unicode-стрелке в логах, и пользователь видит
    # вместо аккуратной ошибки уродливый stack trace.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            # Closed pipes / non-tty streams may reject this — suppress silently.
            with contextlib.suppress(Exception):
                stream.reconfigure(encoding="utf-8", errors="replace")

    root = logging.getLogger(_ROOT_NAME)
    level = logging.DEBUG if os.getenv("WATCHDOG_DEBUG") == "1" else logging.INFO
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)
    handler.setFormatter(
        logging.Formatter(
            fmt="[%(levelname)s] %(asctime)s %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    # Replace handlers in case the runtime added defaults.
    root.handlers = [handler]
    root.propagate = False
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced child logger under the project's root."""
    _configure_root()
    return logging.getLogger(f"{_ROOT_NAME}.{name}")
