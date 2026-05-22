"""Health check script.

Запусти ``python -m src.healthcheck``, чтобы убедиться, что окружение
настроено правильно. Полезно после первой установки и при отладке.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from src.config import ConfigError, load_config
from src.utils.logger import get_logger

logger = get_logger("healthcheck")


def _check_config_file() -> None:
    if not Path("config.yaml").exists():
        raise RuntimeError("Файл config.yaml не найден в корне репозитория.")


def _check_config_valid() -> None:
    load_config()


def _check_secrets() -> None:
    cfg = load_config()
    if not cfg.has_secrets():
        raise RuntimeError("Не все секреты установлены (см. .env / GitHub Secrets).")


def _check_portfolio() -> None:
    from src.portfolio_loader import PortfolioLoader

    cfg = load_config()
    positions = PortfolioLoader(
        portfolio_dir="portfolio", config_tickers=cfg.tickers
    ).load()
    if not positions:
        raise RuntimeError("Портфель пуст: ни CSV, ни tickers в config.yaml.")


def _check_telegram() -> None:
    from src.clients.telegram import TelegramClient

    cfg = load_config()
    tg = TelegramClient(cfg.telegram_bot_token, cfg.telegram_chat_id)
    if not tg.send_message("✅ Healthcheck: Telegram OK"):
        raise RuntimeError("Telegram send_message вернул False.")


def _check_claude() -> None:
    from src.clients.claude import ClaudeClient

    cfg = load_config()
    claude = ClaudeClient(cfg.claude_api_key, cfg.claude.model)
    reply = claude.analyze("Reply with the single word: ok", max_tokens=20)
    if "ok" not in reply.lower():
        raise RuntimeError(f"Неожиданный ответ Claude: {reply!r}")


def _check_sec() -> None:
    from src.clients.sec_edgar import SECEdgarClient

    sec = SECEdgarClient()
    filings = sec.get_recent_filings("0000320193", form_type="4", days=30)  # Apple
    # Apple подаёт Form 4 регулярно; пустой ответ — почти наверняка сетевая проблема.
    if not isinstance(filings, list):
        raise RuntimeError("SEC EDGAR вернул не-список.")


def _check_market_data() -> None:
    from src.clients.market_data import MarketDataClient

    md = MarketDataClient()
    price = md.get_current_price("AAPL")
    if price <= 0:
        raise RuntimeError("MarketDataClient.get_current_price вернул 0 — yfinance молчит.")


def _check_disk() -> None:
    _, _, free = shutil.disk_usage(Path.cwd())
    if free < 100 * 1024 * 1024:  # 100 MB
        raise RuntimeError(f"Мало свободного места: {free // 1024 // 1024} MB")


def run_health_check() -> int:
    checks = [
        ("Config file exists", _check_config_file),
        ("Config is valid", _check_config_valid),
        ("Secrets are set", _check_secrets),
        ("Portfolio loadable", _check_portfolio),
        ("SEC EDGAR accessible", _check_sec),
        ("Market data available", _check_market_data),
        ("Disk space sufficient", _check_disk),
        ("Telegram connection", _check_telegram),
        ("Claude API connection", _check_claude),
    ]

    failed = 0
    for name, fn in checks:
        try:
            fn()
            print(f"✅ {name}")
        except ConfigError as exc:
            print(f"❌ {name}:\n{exc}")
            failed += 1
        except Exception as exc:
            print(f"❌ {name}: {exc}")
            failed += 1

    if failed:
        print(f"\n⚠️  {failed} check(s) failed.")
    else:
        print("\n🎉 Всё на месте. Можно включать workflows.")
    return failed


if __name__ == "__main__":
    sys.exit(run_health_check())
