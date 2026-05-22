"""HTML templates for Telegram notifications.

Все шаблоны — на русском (по умолчанию). Поддержка ``language="en"``
оставлена как точка расширения: переключатель `_TEMPLATES_<LANG>` и
условный выбор внутри :func:`format_signal`.
"""

from __future__ import annotations

from src.monitors.base import Signal
from src.utils.formatting import escape_html, format_severity_emoji

_SEVERITY_TEXT_RU = {
    "low": "Низкая важность",
    "medium": "Средняя важность",
    "high": "Высокая важность",
    "critical": "КРИТИЧНО",
}

_SEVERITY_TEXT_EN = {
    "low": "Low importance",
    "medium": "Medium importance",
    "high": "High importance",
    "critical": "CRITICAL",
}


def format_signal(signal: Signal, language: str = "ru") -> str:
    """Render a :class:`Signal` to a Telegram-HTML string."""
    severity_table = _SEVERITY_TEXT_RU if language == "ru" else _SEVERITY_TEXT_EN
    severity_text = severity_table.get(signal.severity, signal.severity)
    emoji = format_severity_emoji(signal.severity)

    renderer = {
        "insider": _render_insider,
        "analyst": _render_analyst,
        "price": _render_price,
        "news": _render_news,
        "earnings": _render_earnings,
        "macro": _render_macro,
        "volatility": _render_volatility,
    }.get(signal.signal_type, _render_generic)

    body = renderer(signal)
    source = (
        f'\n\n<a href="{escape_html(signal.source_url)}">Источник</a>'
        if signal.source_url
        else ""
    )
    return f"{emoji} <b>{severity_text} — ${escape_html(signal.ticker)}</b>\n\n{body}{source}"


# ---------- Per-type renderers ----------


def _render_insider(signal: Signal) -> str:
    if signal.data.get("cluster"):
        rows = signal.data.get("by_insider") or []
        body = "\n".join(
            f"  • <b>{escape_html(str(name))}</b>: {_money(value)}"
            for name, value in rows
        )
        return (
            f"<b>Кластер инсайдерских продаж</b>\n"
            f"За {signal.data.get('window_days', 30)} дней "
            f"<b>{signal.data.get('insiders_count', '?')}</b> инсайдеров продали "
            f"на сумму <b>{_money(signal.data.get('total_value', 0))}</b>:\n{body}"
        )
    return (
        f"👤 <b>{escape_html(signal.data.get('insider_name', '—'))}</b>"
        f" ({escape_html(signal.data.get('insider_title') or '—')})\n"
        f"📊 Продажа: <b>{_money(signal.data.get('total_value', 0))}</b>"
        f" ({int(signal.data.get('shares', 0)):,} акций)\n"
        f"🗓 {escape_html(signal.data.get('filed_at') or '—')} · SEC Form 4"
    )


def _render_analyst(signal: Signal) -> str:
    direction = signal.data.get("direction", "")
    arrow = "📉" if "down" in direction or "sell" in direction else "📈"
    return (
        f"{arrow} <b>{escape_html(signal.data.get('firm', '—'))}</b>\n"
        f"Рейтинг: {escape_html(signal.data.get('from_grade') or '—')} → "
        f"<b>{escape_html(signal.data.get('to_grade') or '—')}</b>\n"
        f"Действие: {escape_html(signal.data.get('action') or direction)}"
    )


def _render_price(signal: Signal) -> str:
    change = signal.data.get("change_percent", 0.0)
    bench = signal.data.get("benchmark", "SPY")
    bench_change = signal.data.get("benchmark_change_percent", 0.0)
    rel = signal.data.get("relative_strength", 0.0)
    arrow = "📈" if change >= 0 else "📉"
    return (
        f"{arrow} Изменение за день: <b>{_pct(change)}</b>\n"
        f"📊 {bench}: {_pct(bench_change)}\n"
        f"⚖️ Относительно рынка: <b>{_pct(rel)}</b>"
    )


def _render_news(signal: Signal) -> str:
    return (
        f"📰 <b>{escape_html(signal.data.get('publisher') or '—')}</b>\n"
        f"{escape_html(signal.data.get('title') or '')}\n\n"
        f"🤖 <b>Claude:</b> {signal.data.get('score', '?')}/10 — "
        f"{escape_html(signal.data.get('reason') or '')}"
    )


def _render_earnings(signal: Signal) -> str:
    date = signal.data.get("date") or "—"
    eps = signal.data.get("eps_estimate")
    revenue = signal.data.get("revenue_estimate")
    parts = [f"🗓 <b>Earnings:</b> {escape_html(str(date))}"]
    if eps is not None:
        parts.append(f"💹 Ожидание EPS: <b>{eps}</b>")
    if revenue is not None:
        parts.append(f"💰 Ожидание выручки: <b>{_money(revenue)}</b>")
    if signal.data.get("actual_eps") is not None:
        parts.append(
            f"📣 Факт EPS: <b>{signal.data['actual_eps']}</b>"
            f" (сюрприз: {_pct(signal.data.get('eps_surprise_pct') or 0)})"
        )
    return "\n".join(parts)


def _render_macro(signal: Signal) -> str:
    return (
        f"🌐 <b>{escape_html(signal.data.get('event_name') or signal.title)}</b>\n"
        f"🗓 {escape_html(signal.data.get('event_date') or '—')}\n"
        f"{escape_html(signal.description)}"
    )


def _render_volatility(signal: Signal) -> str:
    return f"⚡ {escape_html(signal.description)}"


def _render_generic(signal: Signal) -> str:
    return escape_html(signal.description)


# ---------- Local helpers ----------


def _money(value: float) -> str:
    from src.utils.formatting import format_large_number

    return format_large_number(value)


def _pct(value: float) -> str:
    from src.utils.formatting import format_percent

    return format_percent(value)
