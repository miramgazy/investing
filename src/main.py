"""Claude Portfolio Watchdog — main entry point.

Usage::

    python -m src.main --task=monitor       # hourly monitoring
    python -m src.main --task=daily         # morning summary
    python -m src.main --task=weekly        # weekly PDF report
    python -m src.main --task=demo          # send example notifications
    python -m src.main --task=test          # run smoke setup checks
"""

from __future__ import annotations

import argparse
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from src.clients.claude import ClaudeClient
from src.clients.market_data import MarketDataClient
from src.clients.sec_edgar import SECEdgarClient
from src.clients.telegram import TelegramClient
from src.config import ConfigError, load_config
from src.constants import DEFAULT_SEC_USER_AGENT
from src.monitors.analysts import AnalystMonitor
from src.monitors.base import BaseMonitor, Signal
from src.monitors.earnings import EarningsMonitor
from src.monitors.insider import InsiderMonitor
from src.monitors.macro import MacroMonitor
from src.monitors.news import NewsMonitor
from src.monitors.price import PriceMonitor
from src.monitors.volatility import VolatilityMonitor
from src.portfolio_loader import PortfolioLoader
from src.utils.dedup import SignalDeduplicator
from src.utils.logger import get_logger
from src.utils.templates import format_signal
from src.utils.tickers import TickerUtils

if TYPE_CHECKING:  # pragma: no cover
    from src.portfolio_loader import Position


logger = get_logger("main")


class Application:
    """Glues clients, monitors, reports and Telegram delivery together."""

    def __init__(self) -> None:
        self.config = load_config()
        self.telegram = TelegramClient(
            self.config.telegram_bot_token,
            self.config.telegram_chat_id,
        )
        self.claude = ClaudeClient(
            self.config.claude_api_key, model=self.config.claude.model
        )
        self.sec = SECEdgarClient(user_agent=DEFAULT_SEC_USER_AGENT)
        self.market = MarketDataClient()
        self.tickers = TickerUtils()
        self.deduplicator = SignalDeduplicator()
        self._portfolio: list[Position] | None = None

    # ---------- Properties ----------

    @property
    def portfolio(self) -> list[Position]:
        if self._portfolio is None:
            loader = PortfolioLoader(
                portfolio_dir="portfolio",
                config_tickers=self.config.tickers,
                market_data=self.market,
            )
            self._portfolio = loader.load()
            logger.info("Loaded %d positions", len(self._portfolio))
        return self._portfolio

    # ---------- Tasks ----------

    def run_monitoring(self) -> int:
        logger.info("=" * 60)
        logger.info("Monitoring run started")

        if not self.portfolio:
            self.telegram.send_error(
                "Портфель пуст. Загрузи CSV из IBKR в папку portfolio/ "
                "или укажи тикеры в config.yaml."
            )
            return 1

        # Первый запуск — кеш дедупа ещё пуст → шлём welcome.
        # После приветствия принудительно создаём файл (даже если за этот
        # запуск не будет сигналов), иначе следующий запуск снова сочтёт
        # себя "первым" и отправит welcome повторно.
        if not Path(self.deduplicator.cache_file).exists():
            self._send_welcome()
            self.deduplicator._save_cache()

        monitors = self._build_monitors()
        all_signals: list[Signal] = []

        for monitor in monitors:
            if not monitor.is_enabled():
                logger.info("Skipping %s (disabled in config)", monitor.name)
                continue
            try:
                start = datetime.now()
                signals = monitor.check(self.portfolio)
                elapsed = (datetime.now() - start).total_seconds()
                logger.info(
                    "⏱️  %s: %d signals in %.1fs", monitor.name, len(signals), elapsed
                )
                all_signals.extend(signals)
            except Exception as exc:
                logger.error("Monitor %s failed: %s", monitor.name, exc)
                logger.debug(traceback.format_exc())
                continue

        new_signals = self.deduplicator.filter_new(all_signals)
        logger.info(
            "📊 Found %d signals, %d new after dedup", len(all_signals), len(new_signals)
        )

        for signal in new_signals:
            try:
                self._send_signal(signal)
                self.deduplicator.mark_sent(signal)
            except Exception as exc:
                logger.error("Failed to deliver signal %s: %s", signal.title, exc)

        logger.info("Monitoring run complete. Sent %d notifications.", len(new_signals))
        return 0

    def run_daily_summary(self) -> int:
        logger.info("Generating daily summary…")
        if not self.portfolio:
            return 1
        # Lazy import to keep top of main light.
        from src.reports.daily import DailySummary

        summary = DailySummary(self.config, self.market, self.claude).generate(self.portfolio)
        ok = self.telegram.send_message(summary)
        return 0 if ok else 1

    def run_weekly_report(self) -> int:
        logger.info("Generating weekly PDF report…")
        if not self.portfolio:
            return 1
        from src.reports.weekly_pdf import WeeklyReport

        try:
            pdf_path = WeeklyReport(
                self.config, self.market, self.claude, self.deduplicator
            ).generate(self.portfolio)
        except Exception as exc:
            logger.error("Weekly PDF generation failed: %s", exc)
            logger.debug(traceback.format_exc())
            self.telegram.send_error(
                "Не удалось собрать еженедельный PDF-отчёт. "
                "Проверь логи GitHub Actions."
            )
            return 1

        caption = (
            "📊 <b>Еженедельный отчёт по портфелю</b>\n"
            f"<i>{datetime.now().strftime('%d %B %Y')}</i>\n\n"
            "Открой PDF, чтобы посмотреть полный анализ."
        )
        ok = self.telegram.send_document(pdf_path, caption=caption)
        return 0 if ok else 1

    def run_demo(self) -> int:
        from src.utils.templates import format_signal

        intro = (
            "🎬 <b>ДЕМО-РЕЖИМ</b>\n\n"
            "Сейчас придут примеры всех типов уведомлений, которые ты будешь получать. "
            "Это не реальные сигналы — это примеры формата."
        )
        self.telegram.send_message(intro)

        demo_signals = _demo_signals()
        for signal in demo_signals:
            try:
                self.telegram.send_message(format_signal(signal, language=self.config.reports.language))
            except Exception as exc:
                logger.error("Demo signal failed: %s", exc)
        return 0

    # ---------- Internals ----------

    def _build_monitors(self) -> list[BaseMonitor]:
        # NB: только включённые в config попадут в реальный пайплайн —
        # is_enabled() сверяется отдельно.
        return [
            InsiderMonitor(self.config, self.sec, self.tickers),
            AnalystMonitor(self.config, self.market),
            PriceMonitor(self.config, self.market),
            NewsMonitor(self.config, self.market, self.claude),
            EarningsMonitor(self.config, self.market),
            MacroMonitor(self.config, self.market, self.claude),
            VolatilityMonitor(self.config, self.market),
        ]

    def _send_signal(self, signal: Signal) -> None:
        rendered = format_signal(signal, language=self.config.reports.language)
        self.telegram.send_message(rendered)

    def _send_welcome(self) -> None:
        text = (
            "🎉 <b>Claude Portfolio Watchdog активирован!</b>\n\n"
            "Система начала следить за твоим портфелем 24/7.\n\n"
            "<b>Что отслеживается:</b>\n"
            "✅ Инсайдерские сделки (SEC EDGAR)\n"
            "✅ Изменения рейтингов аналитиков\n"
            "✅ Резкие движения цены\n"
            "✅ Важные новости (фильтр Claude)\n"
            "✅ Earnings calendar\n"
            "✅ Макро-события\n"
            "✅ Волатильность и ротация секторов\n\n"
            "<b>Что ты будешь получать:</b>\n"
            "🔔 Алерты в реальном времени\n"
            "☀️ Утреннюю сводку в 09:00 МСК (будни)\n"
            "📊 Полный PDF-отчёт по воскресеньям в 20:00 МСК\n\n"
            "<i>Удачных инвестиций 📈</i>"
        )
        try:
            self.telegram.send_message(text)
        except Exception as exc:
            logger.warning("Could not send welcome message: %s", exc)


# ---------- Demo data ----------


def _demo_signals() -> list[Signal]:
    """Curated examples of every signal type. Static — for one-shot demo."""
    return [
        Signal(
            signal_type="insider",
            ticker="TSLA",
            severity="critical",
            title="TSLA: кластер инсайдерских продаж",
            description="4 инсайдера продали суммарно $100M+ за 30 дней.",
            data={
                "cluster": True,
                "insiders_count": 4,
                "total_value": 100_000_000,
                "window_days": 30,
                "by_insider": [
                    ("Robyn Denholm", 33_000_000),
                    ("Elon Musk", 25_000_000),
                    ("Vaibhav Taneja", 20_000_000),
                    ("James Murdoch", 22_000_000),
                ],
            },
            source_url="https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=1318605&type=4",
        ),
        Signal(
            signal_type="analyst",
            ticker="AAPL",
            severity="high",
            title="AAPL: понижение от Morgan Stanley",
            description="Morgan Stanley downgrade.",
            data={
                "firm": "Morgan Stanley", "from_grade": "Overweight",
                "to_grade": "Equal-Weight", "action": "downgrade", "direction": "downgrade",
            },
        ),
        Signal(
            signal_type="price",
            ticker="NVDA",
            severity="high",
            title="NVDA: упал на 6.5%",
            description="Сильное движение.",
            data={
                "change_percent": -6.5,
                "benchmark": "SPY",
                "benchmark_change_percent": -0.4,
                "relative_strength": -6.1,
            },
        ),
        Signal(
            signal_type="news",
            ticker="META",
            severity="high",
            title="META: новость от Reuters",
            description="—",
            data={
                "publisher": "Reuters",
                "title": "Meta faces EU antitrust probe over data practices",
                "score": 9,
                "reason": "Регуляторное расследование — материально для бизнеса.",
            },
            source_url="https://www.reuters.com/",
        ),
        Signal(
            signal_type="earnings",
            ticker="MSFT",
            severity="medium",
            title="MSFT: earnings через 2 дня",
            description="—",
            data={
                "date": "2026-05-18",
                "days_to": 2,
                "eps_estimate": 2.85,
                "revenue_estimate": 60_000_000_000,
            },
        ),
        Signal(
            signal_type="macro",
            ticker="MARKET",
            severity="medium",
            title="CPI Release завтра",
            description="Релиз индекса потребительских цен.",
            data={"event_name": "CPI Release", "event_date": "2026-05-12", "days_to": 1},
        ),
        Signal(
            signal_type="volatility",
            ticker="^VIX",
            severity="high",
            title="VIX = 28.4 (порог 25)",
            description="VIX закрылся на 28.4, прирост за день +18.2%.",
            data={"vix": 28.4, "delta_percent": 18.2},
        ),
    ]


# ---------- CLI ----------


def main() -> int:
    parser = argparse.ArgumentParser(description="Claude Portfolio Watchdog")
    parser.add_argument(
        "--task",
        choices=["monitor", "daily", "weekly", "demo", "test"],
        required=True,
        help="Task to run",
    )
    args = parser.parse_args()

    if args.task == "test":
        from src.test_setup import main as test_main

        return test_main()

    try:
        app = Application()
    except ConfigError as exc:
        logger.critical("Config error:\n%s", exc)
        return 1
    except Exception as exc:
        logger.critical("Startup failed: %s", exc)
        logger.debug(traceback.format_exc())
        return 1

    handlers = {
        "monitor": app.run_monitoring,
        "daily": app.run_daily_summary,
        "weekly": app.run_weekly_report,
        "demo": app.run_demo,
    }
    try:
        return handlers[args.task]()
    except Exception as exc:
        logger.critical("Fatal error: %s", exc)
        logger.critical(traceback.format_exc())
        # Best-effort Telegram notification about the crash.
        import contextlib

        with contextlib.suppress(Exception):
            app.telegram.send_error(
                f"🔥 Критическая ошибка ({type(exc).__name__}). "
                "Проверь логи GitHub Actions."
            )
        return 1


if __name__ == "__main__":
    sys.exit(main())
