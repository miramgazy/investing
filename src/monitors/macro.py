"""Macro events monitor.

Без бесплатного API заранее известных макро-релизов реализован самый
надёжный вариант: захардкоженные FOMC-даты и BLS-релизы (CPI/PPI/NFP)
для текущего года, плюс ежемесячные оценки для будущих месяцев. Для CPI
и NFP в США жёсткие правила публикации (2-й вторник месяца / 1-я
пятница), поэтому даты можно вычислять.

Это не идеально, но достаточно, чтобы продукт не зависел от платных
календарных API. Покупатель может уточнить расписание в config через
override (см. CUSTOMIZATION.md).
"""

from __future__ import annotations

from calendar import monthcalendar
from datetime import date, timedelta
from typing import TYPE_CHECKING

from src.monitors.base import BaseMonitor, Signal

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.claude import ClaudeClient
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


# 2026 FOMC schedule — публично известен заранее, безопасно зафиксировать.
# Если год сменится — заполняется заглушкой "1-я среда квартала" (см. ниже).
_FOMC_2026 = [
    date(2026, 1, 28),
    date(2026, 3, 18),
    date(2026, 4, 29),
    date(2026, 6, 17),
    date(2026, 7, 29),
    date(2026, 9, 16),
    date(2026, 10, 28),
    date(2026, 12, 9),
]


class MacroMonitor(BaseMonitor):
    name = "Macro Events Monitor"
    config_flag = "macro"

    def __init__(
        self,
        config,
        market_client: MarketDataClient,
        claude_client: ClaudeClient,
    ) -> None:
        super().__init__(config)
        self.market = market_client
        self.claude = claude_client

    def check(self, positions: list[Position]) -> list[Signal]:
        today = date.today()
        signals: list[Signal] = []

        for event in _upcoming_events(today, window_days=7):
            days_to = (event["date"] - today).days
            severity = self._severity(event, days_to)
            if severity is None:
                continue
            signals.append(
                Signal(
                    signal_type="macro",
                    ticker="MARKET",
                    severity=severity,
                    title=f"{event['name']} {_when(days_to)}"[:80],
                    description=(
                        f"{event['name']} — {event['date'].isoformat()}.\n"
                        f"Событие может затронуть рынок в целом; обратите внимание "
                        f"на сектора {', '.join({p.sector for p in positions if p.sector})}."
                        if any(p.sector for p in positions) else
                        f"{event['name']} — {event['date'].isoformat()}."
                    ),
                    data={
                        "event_name": event["name"],
                        "event_date": event["date"].isoformat(),
                        "days_to": days_to,
                    },
                )
            )
        return signals

    @staticmethod
    def _severity(event: dict, days_to: int) -> str | None:
        if days_to < 0 or days_to > 7:
            return None
        if event["name"].startswith("FOMC"):
            return "high" if days_to <= 1 else "medium"
        if days_to == 0:
            return "high"
        if days_to <= 1:
            return "medium"
        return "low"


# ---------- Event scheduling ----------


def _upcoming_events(today: date, window_days: int) -> list[dict]:
    end = today + timedelta(days=window_days)
    events: list[dict] = []
    for d in _generate_dates(today.year):
        if today <= d <= end:
            events.append(d.__dict__ if False else {"name": _event_name_for(d), "date": d})
    # Sort and dedup.
    events.sort(key=lambda x: x["date"])
    return events


def _generate_dates(year: int) -> list[date]:
    out: list[date] = []
    # FOMC (only 2026 hardcoded; for other years — first Wednesday of every other month).
    if year == 2026:
        out.extend(_FOMC_2026)
    else:
        for month in (1, 3, 5, 6, 7, 9, 11, 12):
            out.append(_nth_weekday(year, month, weekday=2, n=1))

    # CPI — 2nd Tuesday of each month (rule of thumb).
    for month in range(1, 13):
        out.append(_nth_weekday(year, month, weekday=1, n=2))
    # PPI — 2nd Wednesday.
    for month in range(1, 13):
        out.append(_nth_weekday(year, month, weekday=2, n=2))
    # NFP — 1st Friday of each month.
    for month in range(1, 13):
        out.append(_nth_weekday(year, month, weekday=4, n=1))
    return out


def _event_name_for(d: date) -> str:
    """Pick the human label for a date generated above.

    Когда дата попадает в несколько правил — выбираем наиболее значимое.
    """
    if d in _FOMC_2026:
        return "FOMC Decision"
    # NFP — первая пятница месяца.
    if d == _nth_weekday(d.year, d.month, weekday=4, n=1):
        return "Non-Farm Payrolls (NFP)"
    if d == _nth_weekday(d.year, d.month, weekday=1, n=2):
        return "CPI Release"
    if d == _nth_weekday(d.year, d.month, weekday=2, n=2):
        return "PPI Release"
    return "Macro event"


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Return the date of the Nth weekday (0=Mon, 4=Fri) in ``year/month``."""
    cal = monthcalendar(year, month)
    weekdays = [week[weekday] for week in cal if week[weekday] != 0]
    if n - 1 >= len(weekdays):
        return date(year, month, weekdays[-1])
    return date(year, month, weekdays[n - 1])


def _when(days_to: int) -> str:
    if days_to == 0:
        return "сегодня"
    if days_to == 1:
        return "завтра"
    return f"через {days_to} дн."
