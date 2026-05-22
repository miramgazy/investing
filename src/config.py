"""Strict YAML config loader on top of pydantic.

Конфиг репозитория (``config.yaml``) валидируется pydantic-схемой при
каждом запуске — это даёт читаемые ошибки покупателю, который скорее всего
не знает Python. Секреты (``TELEGRAM_BOT_TOKEN`` / ``TELEGRAM_CHAT_ID`` /
``CLAUDE_API_KEY``) подтягиваются из переменных окружения; если запущено
локально и рядом лежит ``.env`` — он подгружается через python-dotenv.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator

# .env подхватываем только локально; в GitHub Actions используются Secrets.
try:  # pragma: no cover - cosmetic
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass


class ConfigError(RuntimeError):
    """Raised with a human-friendly message when config / env are bad."""


# ---------- Sub-models ----------


class MonitoringConfig(BaseModel):
    insider_trades: bool = True
    analyst_ratings: bool = True
    price_movements: bool = True
    news: bool = True
    earnings: bool = True
    macro: bool = True
    volatility: bool = True

    def enabled_count(self) -> int:
        return sum(int(v) for v in self.model_dump().values())


class ThresholdsConfig(BaseModel):
    price_movement_percent: float = Field(default=3.0, ge=0.5, le=20.0)
    news_importance_min: int = Field(default=7, ge=1, le=10)
    insider_min_value_usd: int = Field(default=1_000_000, ge=10_000)
    vix_alert_level: float = Field(default=25.0, ge=15.0)
    earnings_days_before: int = Field(default=3, ge=1, le=14)


class ScheduleConfig(BaseModel):
    monitor_interval: str = "0 13-20 * * 1-5"
    daily_summary: str = "0 6 * * 1-5"
    weekly_report: str = "0 17 * * 0"


class ReportsConfig(BaseModel):
    language: Literal["ru", "en"] = "ru"
    timezone: str = "Europe/Moscow"
    currency: str = "USD"
    benchmark: str = "SPY"


class ClaudeConfig(BaseModel):
    model: str = "claude-sonnet-4-20250514"
    insights_style: Literal["professional", "casual", "detailed"] = "professional"


class PDFConfig(BaseModel):
    theme: Literal["dark", "light"] = "dark"
    accent_color: str = "#00d4ff"

    @field_validator("accent_color")
    @classmethod
    def _validate_hex(cls, v: str) -> str:
        if not (v.startswith("#") and len(v) in (4, 7)):
            raise ValueError("accent_color must be a hex string like '#00d4ff'")
        return v


# ---------- Root model ----------


class Config(BaseModel):
    tickers: list[str] = Field(default_factory=list)
    monitoring: MonitoringConfig = Field(default_factory=MonitoringConfig)
    thresholds: ThresholdsConfig = Field(default_factory=ThresholdsConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    reports: ReportsConfig = Field(default_factory=ReportsConfig)
    claude: ClaudeConfig = Field(default_factory=ClaudeConfig)
    pdf: PDFConfig = Field(default_factory=PDFConfig)

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    claude_api_key: str = ""

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, v: list[str]) -> list[str]:
        return [t.strip().upper() for t in v if t and t.strip()]

    def has_secrets(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id and self.claude_api_key)


# ---------- Loader ----------


def load_config(path: str | Path = "config.yaml") -> Config:
    """Load YAML config and merge env-based secrets.

    Args:
        path: путь к ``config.yaml`` (по умолчанию — в корне репозитория).

    Returns:
        Validated :class:`Config`.

    Raises:
        ConfigError: с понятным сообщением, если файл не найден,
            не валиден или не хватает секретов в env.
    """
    config_path = Path(path)
    if not config_path.exists():
        raise ConfigError(
            f"Не найден конфиг-файл: {config_path.resolve()}\n"
            "Решение: скопируй config.example.yaml в config.yaml и заполни."
        )

    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"Не удалось распарсить config.yaml как YAML:\n{exc}\n\n"
            "Самые частые причины:\n"
            "  · Неправильный отступ (YAML чувствителен к пробелам, табы нельзя)\n"
            "  · Незакрытые кавычки\n"
            "  · Лишние двоеточия\n"
            "Сравни свой файл с config.example.yaml — там образец."
        ) from exc

    try:
        cfg = Config(**raw)
    except ValidationError as exc:
        # pydantic v2 выдаёт читаемые сообщения по полям.
        raise ConfigError(
            "Конфиг невалиден. Подробности:\n" + _format_validation_error(exc)
        ) from exc

    cfg.telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    cfg.telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    cfg.claude_api_key = os.getenv("CLAUDE_API_KEY", "")

    missing = [
        name
        for name, value in (
            ("TELEGRAM_BOT_TOKEN", cfg.telegram_bot_token),
            ("TELEGRAM_CHAT_ID", cfg.telegram_chat_id),
            ("CLAUDE_API_KEY", cfg.claude_api_key),
        )
        if not value
    ]
    if missing:
        raise ConfigError(
            "Не заданы секреты: " + ", ".join(missing) + "\n"
            "Локально: создай файл .env по образцу .env.example\n"
            "GitHub Actions: Settings → Secrets and variables → Actions → "
            "New repository secret."
        )

    return cfg


def _format_validation_error(exc: ValidationError) -> str:
    lines = []
    for err in exc.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "<root>"
        lines.append(f"  · {loc}: {err['msg']}")
    return "\n".join(lines)
