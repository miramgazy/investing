"""Formatting helpers for currency, percentages, large numbers and Telegram HTML.

Все функции тут — чистые и не имеют сторонних эффектов; их используют
шаблоны уведомлений и PDF-отчёты.
"""

from __future__ import annotations

import html
import math
from typing import Final

_SEVERITY_EMOJI: Final[dict[str, str]] = {
    "low": "ℹ️",
    "medium": "⚠️",
    "high": "🚨",
    "critical": "🆘",
}

_CURRENCY_SIGN: Final[dict[str, str]] = {
    "USD": "$",
    "EUR": "€",
    "GBP": "£",
    "RUB": "₽",
}


def format_currency(value: float, currency: str = "USD") -> str:
    """Render a money amount with thousands separator and 2 decimals.

    >>> format_currency(1234.5)
    '$1,234.50'
    >>> format_currency(-89.1, 'EUR')
    '-€89.10'
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    sign = "-" if value < 0 else ""
    symbol = _CURRENCY_SIGN.get(currency, f"{currency} ")
    return f"{sign}{symbol}{abs(value):,.2f}"


def format_percent(value: float, with_sign: bool = True, decimals: int = 2) -> str:
    """Render a percentage with optional explicit sign.

    >>> format_percent(1.234)
    '+1.23%'
    >>> format_percent(-0.5, with_sign=False)
    '0.50%'
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    sign = ""
    if with_sign:
        sign = "+" if value > 0 else ("-" if value < 0 else "")
    return f"{sign}{abs(value):.{decimals}f}%"


def format_large_number(value: float, currency: str = "USD") -> str:
    """Compact representation: ``$1.23B`` / ``$45M`` / ``$123K``.

    Below $1,000 falls back to :func:`format_currency`.
    """
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return "—"
    sign = "-" if value < 0 else ""
    abs_value = abs(value)
    symbol = _CURRENCY_SIGN.get(currency, f"{currency} ")

    if abs_value >= 1_000_000_000:
        return f"{sign}{symbol}{abs_value / 1_000_000_000:.2f}B"
    if abs_value >= 1_000_000:
        return f"{sign}{symbol}{abs_value / 1_000_000:.2f}M"
    if abs_value >= 1_000:
        return f"{sign}{symbol}{abs_value / 1_000:.1f}K"
    return format_currency(value, currency)


def escape_html(text: str) -> str:
    """Escape ``< > &`` for the Telegram ``parse_mode=HTML`` payload.

    Telegram supports a small HTML subset — we never want user data to
    accidentally inject tags like ``<script>`` or even ``<b>``.
    """
    if text is None:
        return ""
    return html.escape(str(text), quote=False)


def format_severity_emoji(severity: str) -> str:
    """Map severity string to a single visual emoji."""
    return _SEVERITY_EMOJI.get(severity.lower(), "•")


def truncate_text(text: str, max_length: int, suffix: str = "…") -> str:
    """Hard-truncate ``text`` to ``max_length`` characters with ``suffix``."""
    if text is None:
        return ""
    if len(text) <= max_length:
        return text
    if max_length <= len(suffix):
        return text[:max_length]
    return text[: max_length - len(suffix)] + suffix


def format_change(value: float, currency: str = "USD") -> str:
    """``+$12.34 (+1.23%)`` style change string used in headers."""
    return f"{format_currency(value, currency)}"
