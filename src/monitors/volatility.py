"""Volatility / sector rotation / portfolio correlation monitor."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from src.monitors.base import BaseMonitor, Signal

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.market_data import MarketDataClient
    from src.portfolio_loader import Position


_SECTOR_ETFS = [
    ("XLK", "Technology"),
    ("XLF", "Financials"),
    ("XLE", "Energy"),
    ("XLV", "Healthcare"),
    ("XLI", "Industrials"),
    ("XLP", "Consumer Staples"),
    ("XLY", "Consumer Discretionary"),
    ("XLU", "Utilities"),
    ("XLB", "Materials"),
    ("XLRE", "Real Estate"),
    ("XLC", "Communications"),
]


class VolatilityMonitor(BaseMonitor):
    name = "Volatility Monitor"
    config_flag = "volatility"

    def __init__(self, config, market_client: MarketDataClient) -> None:
        super().__init__(config)
        self.market = market_client
        self.vix_threshold = config.thresholds.vix_alert_level

    def check(self, positions: list[Position]) -> list[Signal]:
        signals: list[Signal] = []
        try:
            vix_sig = self._check_vix()
            if vix_sig:
                signals.append(vix_sig)
        except Exception as exc:
            self.logger.warning("VIX check failed: %s", exc)

        try:
            rotation_sig = self._check_sector_rotation(positions)
            if rotation_sig:
                signals.append(rotation_sig)
        except Exception as exc:
            self.logger.warning("Sector rotation check failed: %s", exc)

        try:
            corr_sig = self._check_portfolio_correlation(positions)
            if corr_sig:
                signals.append(corr_sig)
        except Exception as exc:
            self.logger.warning("Correlation check failed: %s", exc)

        return signals

    # ---------- VIX ----------

    def _check_vix(self) -> Signal | None:
        hist = self.market.get_price_history("^VIX", period="5d", interval="1d")
        if hist is None or hist.empty or "Close" not in hist.columns:
            return None
        closes = hist["Close"].dropna()
        if closes.empty:
            return None
        latest = float(closes.iloc[-1])
        prev = float(closes.iloc[-2]) if len(closes) > 1 else latest
        delta_pct = (latest / prev - 1.0) * 100.0 if prev else 0.0

        if latest < self.vix_threshold and abs(delta_pct) < 15.0:
            return None
        severity = "critical" if latest >= 35 else ("high" if latest >= self.vix_threshold else "medium")
        return Signal(
            signal_type="volatility",
            ticker="^VIX",
            severity=severity,
            title=f"VIX = {latest:.1f} (порог {self.vix_threshold:.0f})"[:80],
            description=(
                f"VIX закрылся на {latest:.1f}, прирост за день {delta_pct:+.1f}%. "
                "Повышенный страх на рынке — стоит проверить экспозицию портфеля."
            ),
            data={"vix": latest, "delta_percent": delta_pct},
        )

    # ---------- Sector rotation ----------

    def _check_sector_rotation(self, positions: list[Position]) -> Signal | None:
        rotations: dict[str, float] = {}
        for ticker, sector in _SECTOR_ETFS:
            hist = self.market.get_price_history(ticker, period="1mo", interval="1d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            closes = hist["Close"].dropna()
            if len(closes) < 5:
                continue
            weekly_change = (float(closes.iloc[-1]) / float(closes.iloc[-5]) - 1.0) * 100.0
            rotations[sector] = weekly_change

        if not rotations:
            return None

        # Если значительная доля портфеля в худшем секторе — повышаем severity.
        ranked = sorted(rotations.items(), key=lambda x: x[1])
        worst_sector, worst_change = ranked[0]
        best_sector, best_change = ranked[-1]

        portfolio_share_in_worst = sum(
            1 for p in positions if p.sector == worst_sector
        ) / max(len(positions), 1)

        severity = "medium" if portfolio_share_in_worst >= 0.3 else "low"
        if worst_change > -2.0 and best_change < 2.0:
            return None  # no real rotation yet

        return Signal(
            signal_type="volatility",
            ticker="SECTORS",
            severity=severity,
            title=f"Sector rotation: {best_sector} +{best_change:.1f}%, {worst_sector} {worst_change:.1f}%"[:80],
            description=(
                f"За последнюю неделю лидер по секторам — {best_sector} ({best_change:+.1f}%),"
                f" аутсайдер — {worst_sector} ({worst_change:+.1f}%). "
                f"Доля портфеля в худшем секторе: {portfolio_share_in_worst*100:.0f}%."
            ),
            data={"rotation": rotations, "share_in_worst": portfolio_share_in_worst},
        )

    # ---------- Internal correlation ----------

    def _check_portfolio_correlation(self, positions: list[Position]) -> Signal | None:
        if len(positions) < 3:
            return None
        frames: dict[str, pd.Series] = {}
        for pos in positions:
            hist = self.market.get_price_history(pos.ticker, period="3mo", interval="1d")
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            returns = hist["Close"].dropna().pct_change().dropna()
            if len(returns) > 10:
                frames[pos.ticker] = returns
        if len(frames) < 3:
            return None

        combined = pd.concat(frames.values(), axis=1, keys=frames.keys()).dropna()
        if combined.empty:
            return None
        corr = combined.corr()
        # Average of off-diagonal correlations.
        mask = ~pd.DataFrame(False, index=corr.index, columns=corr.columns)
        for ticker in corr.index:
            mask.loc[ticker, ticker] = False
        avg_corr = corr.where(mask).stack().mean()
        if pd.isna(avg_corr):
            return None
        if avg_corr < 0.8:
            return None

        return Signal(
            signal_type="volatility",
            ticker="PORTFOLIO",
            severity="medium",
            title=f"Высокая внутренняя корреляция портфеля: {avg_corr:.2f}"[:80],
            description=(
                f"Средняя корреляция между позициями: {avg_corr:.2f} (>0.8). "
                "При негативном движении рынка все позиции, скорее всего, "
                "пойдут вниз синхронно — концентрационный риск."
            ),
            data={"avg_correlation": float(avg_corr)},
        )
