"""Daily morning summary — HTML text for one Telegram message.

Структура (под капотом — кеш market data, чтобы не дёргать yfinance 5 раз
по SPY/QQQ/VIX/бенчмарку):

    ☀️ УТРЕННЯЯ СВОДКА
    📊 Рынок за ночь
    💼 Портфель
    📈 Лидеры
    📉 Аутсайдеры
    📅 События сегодня
    💡 Наблюдение Claude
"""

from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING

from src.analytics.insights import InsightsGenerator
from src.analytics.performance import PerformanceAnalytics
from src.utils.formatting import (
    escape_html,
    format_currency,
    format_percent,
)
from src.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.claude import ClaudeClient
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


class DailySummary:
    def __init__(
        self,
        config,
        market_client: MarketDataClient,
        claude_client: ClaudeClient,
    ) -> None:
        self.config = config
        self.market = market_client
        self.claude = claude_client
        self.performance = PerformanceAnalytics(market_client)
        self.insights = InsightsGenerator(claude_client)
        self.logger = get_logger("daily")

    # ---------- Public ----------

    def generate(self, positions: list[Position]) -> str:
        market = self._market_overview()
        portfolio_perf = self._portfolio_change(positions)
        movers = self.performance.get_top_movers(positions, period="1w", n=3)
        events = self._today_events(positions)
        observation = self.insights.generate_daily_observation(
            portfolio_change=portfolio_perf,
            market_context=market,
            signals_today=[],
        )
        return self._render(market, portfolio_perf, movers, events, observation)

    # ---------- Building blocks ----------

    def _market_overview(self) -> dict:
        out: dict[str, dict] = {}
        for ticker, label in (("SPY", "S&P 500"), ("QQQ", "Nasdaq 100"), ("^VIX", "VIX")):
            change = self._daily_change(ticker)
            current = self._latest_close(ticker)
            out[ticker] = {"label": label, "change_pct": change, "value": current}
        return out

    def _portfolio_change(self, positions: list[Position]) -> dict:
        total_today = 0.0
        total_yesterday = 0.0
        for pos in positions:
            hist = self.market.get_price_history(pos.ticker, period="5d", interval="1d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 2:
                continue
            qty = pos.quantity or 0
            total_today += float(closes.iloc[-1]) * qty
            total_yesterday += float(closes.iloc[-2]) * qty

        change_usd = total_today - total_yesterday
        change_pct = (
            (total_today / total_yesterday - 1.0) * 100.0 if total_yesterday else 0.0
        )
        return {
            "value": total_today,
            "change_usd": change_usd,
            "change_pct": change_pct,
        }

    def _today_events(self, positions: list[Position]) -> list[str]:
        events: list[str] = []
        today = date.today().isoformat()
        for pos in positions[:10]:  # ограничим обзор, чтобы не дёргать yf на 100+ тикерах
            try:
                cal = self.market.get_earnings_calendar(pos.ticker)
            except Exception:
                continue
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            if not dates:
                continue
            first = dates[0] if isinstance(dates, list) else dates
            try:
                first_iso = first.date().isoformat() if hasattr(first, "date") else str(first)[:10]
            except Exception:
                continue
            if first_iso == today:
                events.append(f"📣 Earnings сегодня: ${pos.ticker}")
        return events

    def _daily_change(self, ticker: str) -> float:
        hist = self.market.get_price_history(ticker, period="5d", interval="1d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            return 0.0
        closes = hist["Close"].dropna()
        if len(closes) < 2:
            return 0.0
        return (float(closes.iloc[-1]) / float(closes.iloc[-2]) - 1.0) * 100.0

    def _latest_close(self, ticker: str) -> float:
        hist = self.market.get_price_history(ticker, period="5d", interval="1d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            return 0.0
        closes = hist["Close"].dropna()
        return float(closes.iloc[-1]) if not closes.empty else 0.0

    # ---------- Rendering ----------

    def _render(
        self,
        market: dict,
        portfolio: dict,
        movers: dict,
        events: list[str],
        observation: str,
    ) -> str:
        spy = market.get("SPY", {})
        qqq = market.get("QQQ", {})
        vix = market.get("^VIX", {})
        vix_status = (
            "повышенная" if vix.get("value", 0) >= self.config.thresholds.vix_alert_level
            else "спокойно"
        )

        leaders_lines = "\n".join(
            f"   {i+1}. ${escape_html(t)}: <b>{format_percent(p)}</b>"
            for i, (t, p) in enumerate(movers.get("leaders", []))
        ) or "   —"
        laggards_lines = "\n".join(
            f"   {i+1}. ${escape_html(t)}: <b>{format_percent(p)}</b>"
            for i, (t, p) in enumerate(movers.get("laggards", []))
        ) or "   —"
        events_block = "\n".join(events) if events else "Важных событий нет."

        return (
            "☀️ <b>УТРЕННЯЯ СВОДКА ПО ПОРТФЕЛЮ</b>\n"
            f"<i>{datetime.now().strftime('%d %B %Y · %H:%M')}</i>\n\n"
            "📊 <b>Рынок за ночь:</b>\n"
            f"   S&amp;P 500: <b>{format_percent(spy.get('change_pct', 0.0))}</b>\n"
            f"   Nasdaq 100: <b>{format_percent(qqq.get('change_pct', 0.0))}</b>\n"
            f"   VIX: <b>{vix.get('value', 0):.1f}</b> ({vix_status})\n\n"
            "💼 <b>Твой портфель:</b>\n"
            f"   Стоимость: <b>{format_currency(portfolio['value'], self.config.reports.currency)}</b>\n"
            f"   За день: <b>{format_currency(portfolio['change_usd'], self.config.reports.currency)}</b>"
            f" ({format_percent(portfolio['change_pct'])})\n\n"
            f"📈 <b>Лидеры за неделю:</b>\n{leaders_lines}\n\n"
            f"📉 <b>Аутсайдеры:</b>\n{laggards_lines}\n\n"
            f"📅 <b>События сегодня:</b>\n{events_block}\n\n"
            f"💡 <b>Наблюдение Claude:</b>\n{escape_html(observation)}\n\n"
            "<i>Полный отчёт — в воскресенье вечером.</i>"
        )
