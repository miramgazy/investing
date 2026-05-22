"""SEC EDGAR Form 4 insider-trade monitor.

Логика:
1. Для каждой позиции получаем CIK → последние Form 4 за окно.
2. Каждую подачу анализируем: тип сделки, имя/должность, сумма.
   Severity по сумме:
       <  $1M  → не уведомляем (низкая значимость);
       <  $10M → medium;
       <  $50M → high;
       >= $50M → critical.
3. Дополнительно — детектор кластера: если в окне cluster_window_days
   подано ``cluster_count``+ продаж от РАЗНЫХ инсайдеров с суммой ≥ порога,
   выдаём сигнал ``critical`` с severity 'critical'.
"""

from __future__ import annotations

from collections import defaultdict
from typing import TYPE_CHECKING

from src.monitors.base import BaseMonitor, Signal
from src.utils.formatting import format_large_number

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.sec_edgar import SECEdgarClient
    from src.portfolio_loader import Position
    from src.utils.tickers import TickerUtils


_CLUSTER_WINDOW_DAYS = 30
_CLUSTER_MIN_INSIDERS = 3
_SELL_CODES = {"S", "D"}  # S = open-market sale, D = disposition non-derivative.


class InsiderMonitor(BaseMonitor):
    name = "Insider Trades Monitor"
    config_flag = "insider_trades"

    def __init__(
        self,
        config,
        sec_client: SECEdgarClient,
        ticker_utils: TickerUtils,
    ) -> None:
        super().__init__(config)
        self.sec = sec_client
        self.tickers = ticker_utils
        self.min_value = config.thresholds.insider_min_value_usd

    def check(self, positions: list[Position]) -> list[Signal]:
        signals: list[Signal] = []

        for position in positions:
            try:
                cik = self.tickers.get_cik(position.ticker)
                if not cik:
                    self.logger.debug("No CIK for %s, skipping", position.ticker)
                    continue

                recent_filings = self.sec.get_recent_filings(cik, form_type="4", days=1)
                for filing in recent_filings:
                    sig = self._build_filing_signal(position.ticker, cik, filing)
                    if sig:
                        signals.append(sig)

                # Кластер требует более широкого окна.
                cluster_filings = self.sec.get_recent_filings(
                    cik, form_type="4", days=_CLUSTER_WINDOW_DAYS
                )
                cluster_signal = self._build_cluster_signal(
                    position.ticker, cik, cluster_filings
                )
                if cluster_signal:
                    signals.append(cluster_signal)
            except Exception as exc:
                self.logger.error("Insider check failed for %s: %s", position.ticker, exc)
                continue

        return signals

    # ---------- Single filing ----------

    def _build_filing_signal(
        self, ticker: str, cik: str, filing: dict
    ) -> Signal | None:
        details = self.sec.get_form4_details(cik, filing.get("accession_number", ""))
        if not details:
            return None
        if details.get("transaction_type") not in _SELL_CODES:
            # Мы интересуемся прежде всего продажами; покупки тоже могут быть
            # значимы, но шум превышает сигнал — оставим на Pro-тиер.
            return None
        total = details.get("total_value", 0.0)
        if total < self.min_value:
            return None

        severity = _severity_for_amount(total)
        title = f"{ticker}: {details['insider_name']} продал {format_large_number(total)}"

        return Signal(
            signal_type="insider",
            ticker=ticker,
            severity=severity,
            title=title[:80],
            description=(
                f"{details['insider_name']} ({details['insider_title'] or '—'})\n"
                f"Продажа: {format_large_number(total)} ({int(details['shares']):,} акций "
                f"× ${details['price_per_share']:.2f})\n"
                f"Дата: {filing.get('filed_at', '?')}"
            ),
            data={
                "insider_name": details["insider_name"],
                "insider_title": details["insider_title"],
                "transaction_type": details["transaction_type"],
                "total_value": total,
                "shares": details["shares"],
                "filed_at": filing.get("filed_at"),
                "accession_number": filing.get("accession_number"),
            },
            source_url=self.sec.get_company_filings_url(cik),
        )

    # ---------- Cluster detection ----------

    def _build_cluster_signal(
        self, ticker: str, cik: str, filings: list[dict]
    ) -> Signal | None:
        by_insider: dict[str, float] = defaultdict(float)
        for filing in filings:
            details = self.sec.get_form4_details(cik, filing.get("accession_number", ""))
            if not details:
                continue
            if details.get("transaction_type") not in _SELL_CODES:
                continue
            total = details.get("total_value", 0.0)
            if total < self.min_value:
                continue
            by_insider[details["insider_name"]] += total

        if len(by_insider) < _CLUSTER_MIN_INSIDERS:
            return None

        total_sold = sum(by_insider.values())
        ranked = sorted(by_insider.items(), key=lambda x: x[1], reverse=True)
        body = "\n".join(
            f"  • {name}: {format_large_number(value)}" for name, value in ranked
        )

        return Signal(
            signal_type="insider",
            ticker=ticker,
            severity="critical",
            title=f"{ticker}: кластер инсайдерских продаж ({len(by_insider)} человек)",
            description=(
                f"За {_CLUSTER_WINDOW_DAYS} дней {len(by_insider)} инсайдеров "
                f"продали суммарно {format_large_number(total_sold)}:\n{body}"
            ),
            data={
                "cluster": True,
                "insiders_count": len(by_insider),
                "total_value": total_sold,
                "window_days": _CLUSTER_WINDOW_DAYS,
                "by_insider": ranked,
            },
            source_url=self.sec.get_company_filings_url(cik),
        )


def _severity_for_amount(amount: float) -> str:
    if amount >= 50_000_000:
        return "critical"
    if amount >= 10_000_000:
        return "high"
    return "medium"
