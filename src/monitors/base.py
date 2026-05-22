"""Common types for all monitors: :class:`Signal` dataclass and
:class:`BaseMonitor` ABC.

Каждый монитор обязан:
* объявить :pyattr:`BaseMonitor.name` (человекочитаемое имя);
* реализовать :pymeth:`BaseMonitor.check` (возвращает список
  :class:`Signal`'ов, пустой — это норма);
* по желанию переопределить :pymeth:`BaseMonitor.is_enabled`.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from src.utils.logger import get_logger

SignalType = Literal[
    "insider", "analyst", "price", "news", "earnings", "macro", "volatility"
]
Severity = Literal["low", "medium", "high", "critical"]

SEVERITY_ORDER: dict[str, int] = {
    "low": 0, "medium": 1, "high": 2, "critical": 3,
}


@dataclass
class Signal:
    signal_type: SignalType
    ticker: str
    severity: Severity
    title: str
    description: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
    source_url: str = ""

    def unique_id(self) -> str:
        """Stable hash of (type, ticker, date, key data) — used by dedup cache."""
        date = self.timestamp.strftime("%Y-%m-%d")
        # Сериализуем data детерминированно — sorted keys + str().
        payload_keys = sorted(self.data.keys())
        payload = "|".join(f"{k}={self.data[k]}" for k in payload_keys)
        raw = f"{self.signal_type}|{self.ticker}|{date}|{payload}".encode()
        digest = hashlib.sha1(raw).hexdigest()[:12]
        return f"{self.signal_type}_{self.ticker}_{date}_{digest}"


class BaseMonitor(ABC):
    """Abstract parent of every monitor implementation."""

    #: Override in subclasses.
    name: str = "Unnamed Monitor"

    #: Маппится на ``config.monitoring.<flag>`` — переопределяется наследниками.
    config_flag: str = ""

    def __init__(self, config, **_: Any) -> None:
        self.config = config
        self.logger = get_logger(self.__class__.__name__)

    @abstractmethod
    def check(self, positions: list) -> list[Signal]:
        """Return new signals discovered for ``positions``."""

    def is_enabled(self) -> bool:
        """Look at ``config.monitoring.<config_flag>``; default ``True``."""
        if not self.config_flag:
            return True
        return bool(getattr(self.config.monitoring, self.config_flag, True))
