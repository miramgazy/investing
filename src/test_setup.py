"""Smoke-test script for verifying basic setup.

Usage::

    python -m src.test_setup

Проверяет шаг за шагом:
    1. Config грузится и валиден.
    2. Тестовое сообщение уходит в Telegram.
    3. Claude отвечает на тестовый запрос.

После реализации ПРОМПТов 3–4 в этом скрипте дописываются проверки
загрузки портфеля и работы мониторов.
"""

from __future__ import annotations

import sys

from src.config import ConfigError, load_config


def main() -> int:
    print("🧪 Testing Claude Portfolio Watchdog setup...\n")

    # 1. Config -----------------------------------------------------------------
    print("1️⃣  Loading config...")
    try:
        config = load_config()
    except ConfigError as exc:
        print(f"   ❌ Config error:\n{exc}")
        return 1

    enabled = config.monitoring.enabled_count()
    print("   ✅ Config loaded successfully")
    print(f"   Language: {config.reports.language}")
    print(f"   Timezone: {config.reports.timezone}")
    print(f"   Monitoring enabled: {enabled}/7 types")
    print(f"   Tickers in config: {len(config.tickers)}")

    # 2. Telegram ---------------------------------------------------------------
    print("\n2️⃣  Testing Telegram...")
    try:
        from src.clients.telegram import TelegramClient

        tg = TelegramClient(config.telegram_bot_token, config.telegram_chat_id)
        ok = tg.send_message(
            "🧪 <b>Test message</b>\n\n"
            "Claude Portfolio Watchdog setup test.\n"
            "Если ты видишь это сообщение — Telegram-канал настроен правильно."
        )
        if not ok:
            print("   ❌ Failed to send message")
            return 1
        print("   ✅ Telegram message sent")
    except Exception as exc:
        print(f"   ❌ Telegram error: {exc}")
        return 1

    # 3. Claude -----------------------------------------------------------------
    print("\n3️⃣  Testing Claude API...")
    try:
        from src.clients.claude import ClaudeClient

        claude = ClaudeClient(config.claude_api_key, config.claude.model)
        reply = claude.analyze(
            "Say 'Hello from Claude!' in exactly 5 words.", max_tokens=50
        )
        print(f"   ✅ Claude response: {reply}")
    except Exception as exc:
        print(f"   ❌ Claude error: {exc}")
        return 1

    # 4. Portfolio loader -- ПРОМПТ 3 будет дополнять --------------------------
    try:
        from src.portfolio_loader import PortfolioLoader  # type: ignore

        if hasattr(PortfolioLoader, "load"):
            print("\n4️⃣  Testing Portfolio Loader...")
            loader = PortfolioLoader(portfolio_dir="portfolio", config_tickers=config.tickers)
            positions = loader.load()
            print(f"   ✅ Loaded {len(positions)} positions")
            for pos in positions[:5]:
                print(f"      {pos.ticker}: {pos.quantity} @ ${pos.average_cost:.2f}")
            if not positions:
                print("   ⚠️ No positions found. Add CSV to portfolio/ or tickers to config.yaml.")
    except (ImportError, AttributeError):
        # PortfolioLoader ещё не реализован — это нормально на этапе ПРОМПТ 2.
        pass
    except Exception as exc:
        print(f"   ❌ Portfolio loader error: {exc}")

    print("\n🎉 All checks passed. Ready for the next step.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
