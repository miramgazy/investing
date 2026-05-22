"""matplotlib chart factories for the weekly PDF.

All charts emit a PNG to a :class:`BytesIO` ready to be wrapped in a
``reportlab.platypus.Image``. Colour palette is sourced exclusively from
:class:`PDFTheme` — no default matplotlib colours leak through.
"""

from __future__ import annotations

from io import BytesIO
from typing import TYPE_CHECKING

import matplotlib

matplotlib.use("Agg")  # headless rendering — нужно для GitHub Actions
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

if TYPE_CHECKING:  # pragma: no cover
    from src.portfolio_loader import Position
    from src.reports.pdf_templates import PDFTheme

from src.monitors.base import Signal


class ChartGenerator:
    def __init__(self, theme: PDFTheme) -> None:
        self.theme = theme
        self._apply_style()

    # ---------- Styling ----------

    def _apply_style(self) -> None:
        plt.style.use("dark_background" if self.theme.theme_name == "dark" else "default")
        plt.rcParams.update(
            {
                "font.family": "sans-serif",
                "font.sans-serif": ["DejaVu Sans", "Arial", "sans-serif"],
                "axes.facecolor": _hex(self.theme.bg_secondary),
                "figure.facecolor": _hex(self.theme.bg_primary),
                "axes.edgecolor": _hex(self.theme.divider),
                "axes.labelcolor": _hex(self.theme.text_primary),
                "text.color": _hex(self.theme.text_primary),
                "xtick.color": _hex(self.theme.text_secondary),
                "ytick.color": _hex(self.theme.text_secondary),
                "grid.color": _hex(self.theme.divider),
                "grid.linestyle": "--",
                "grid.alpha": 0.35,
                "axes.spines.top": False,
                "axes.spines.right": False,
            }
        )

    # ---------- Charts ----------

    def portfolio_value_chart(
        self,
        portfolio_history: pd.Series,
        benchmark_history: pd.Series,
        benchmark_label: str = "S&P 500 (SPY)",
    ) -> BytesIO:
        """Normalize both series to 100 and draw two lines."""
        fig, ax = plt.subplots(figsize=(10, 4.5))

        if not portfolio_history.empty:
            pn = (portfolio_history / portfolio_history.iloc[0]) * 100
            ax.plot(pn.index, pn.values, color=_hex(self.theme.accent),
                    linewidth=2.5, label="Your Portfolio")
        if not benchmark_history.empty:
            bn = (benchmark_history / benchmark_history.iloc[0]) * 100
            ax.plot(bn.index, bn.values, color=_hex(self.theme.text_secondary),
                    linewidth=1.5, linestyle="--", label=benchmark_label)

        ax.set_ylabel("Index (start = 100)")
        ax.legend(loc="best", framealpha=0.9)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.grid(True, alpha=0.3)
        return self._to_bytes(fig)

    def portfolio_composition_pie(self, positions: list[Position]) -> BytesIO:
        labels = [p.ticker for p in positions]
        values = [max(p.market_value or p.total_cost or 0.0, 0.0) for p in positions]
        # Если все нули — нарисуем пустую заглушку.
        if not values or sum(values) == 0:
            return self._empty_chart("No position data")

        # Cap a long tail at top-8 + "Other".
        order = np.argsort(values)[::-1]
        top_idx = order[:8]
        rest_idx = order[8:]
        top_labels = [labels[i] for i in top_idx]
        top_values = [values[i] for i in top_idx]
        if len(rest_idx) > 0:
            top_labels.append("Other")
            top_values.append(sum(values[i] for i in rest_idx))

        palette = self._palette(len(top_labels))
        fig, ax = plt.subplots(figsize=(7, 5))
        ax.pie(
            top_values,
            labels=top_labels,
            colors=palette,
            autopct="%1.1f%%",
            wedgeprops={"edgecolor": _hex(self.theme.bg_primary), "linewidth": 1.5},
            textprops={"color": _hex(self.theme.text_primary), "fontsize": 9},
        )
        return self._to_bytes(fig)

    def sector_distribution_bar(self, sector_share: dict[str, float]) -> BytesIO:
        if not sector_share:
            return self._empty_chart("No sector data")
        sectors = list(sector_share.keys())
        values = [v * 100 for v in sector_share.values()]
        fig, ax = plt.subplots(figsize=(8, 4))
        bars = ax.barh(sectors, values, color=_hex(self.theme.accent), alpha=0.85)
        for bar, val in zip(bars, values, strict=False):
            ax.text(
                bar.get_width() + 0.4, bar.get_y() + bar.get_height() / 2,
                f"{val:.1f}%", color=_hex(self.theme.text_primary),
                va="center", fontsize=9,
            )
        ax.set_xlabel("% of portfolio")
        ax.grid(axis="x", alpha=0.3)
        return self._to_bytes(fig)

    def correlation_heatmap(self, correlations: pd.DataFrame) -> BytesIO:
        if correlations is None or correlations.empty:
            return self._empty_chart("No correlation data")
        fig, ax = plt.subplots(figsize=(6, 5))
        im = ax.imshow(correlations.values, cmap="coolwarm", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(correlations.columns)))
        ax.set_yticks(range(len(correlations.index)))
        ax.set_xticklabels(correlations.columns, rotation=45, ha="right", fontsize=8)
        ax.set_yticklabels(correlations.index, fontsize=8)
        for i in range(len(correlations.index)):
            for j in range(len(correlations.columns)):
                ax.text(
                    j, i, f"{correlations.values[i, j]:.2f}",
                    ha="center", va="center", color="white", fontsize=7,
                )
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
        return self._to_bytes(fig)

    def position_mini_chart(self, ticker: str, history: pd.Series) -> BytesIO:
        fig, ax = plt.subplots(figsize=(4, 1.6))
        if history is not None and not history.empty:
            colour = _hex(self.theme.success if history.iloc[-1] >= history.iloc[0] else self.theme.danger)
            ax.plot(history.index, history.values, color=colour, linewidth=1.6)
            ax.fill_between(history.index, history.values, history.min(), color=colour, alpha=0.15)
        ax.set_title(f"${ticker}", loc="left", fontsize=10)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        return self._to_bytes(fig)

    def signals_timeline(self, signals: list[Signal]) -> BytesIO:
        if not signals:
            return self._empty_chart("No signals this week")
        severity_to_y = {"low": 0, "medium": 1, "high": 2, "critical": 3}
        sev_color = {
            "low": self.theme.text_secondary,
            "medium": self.theme.warning,
            "high": self.theme.danger,
            "critical": self.theme.danger,
        }
        xs = [s.timestamp for s in signals]
        ys = [severity_to_y.get(s.severity, 1) for s in signals]
        colours = [_hex(sev_color.get(s.severity, self.theme.text_secondary)) for s in signals]
        fig, ax = plt.subplots(figsize=(9, 3.5))
        ax.scatter(xs, ys, c=colours, s=80, alpha=0.85, edgecolors=_hex(self.theme.bg_primary))
        ax.set_yticks(list(severity_to_y.values()))
        ax.set_yticklabels(list(severity_to_y.keys()))
        ax.set_title("Signals timeline", fontsize=12, pad=10)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d %b"))
        ax.grid(True, alpha=0.3)
        return self._to_bytes(fig)

    def returns_distribution(self, returns: pd.Series) -> BytesIO:
        if returns is None or returns.empty:
            return self._empty_chart("No return data")
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.hist(returns.values * 100, bins=30, color=_hex(self.theme.accent), alpha=0.85)
        ax.axvline(0, color=_hex(self.theme.text_secondary), linewidth=1)
        ax.set_xlabel("Daily return, %")
        ax.set_title("Daily return distribution", fontsize=12, pad=12)
        return self._to_bytes(fig)

    # ---------- Helpers ----------

    def _palette(self, n: int) -> list[str]:
        base = [
            self.theme.accent,
            self.theme.success,
            self.theme.warning,
            self.theme.danger,
            self.theme.text_secondary,
        ]
        # Repeat / shift hues if more than 5 slices.
        return [_hex(base[i % len(base)]) for i in range(n)]

    def _empty_chart(self, message: str) -> BytesIO:
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.axis("off")
        ax.text(0.5, 0.5, message, ha="center", va="center",
                color=_hex(self.theme.text_secondary), fontsize=12)
        return self._to_bytes(fig)

    def _to_bytes(self, fig) -> BytesIO:
        buf = BytesIO()
        fig.savefig(
            buf, format="png", dpi=150, bbox_inches="tight",
            facecolor=fig.get_facecolor(),
        )
        plt.close(fig)
        buf.seek(0)
        return buf


def _hex(color) -> str:
    """HexColor → matplotlib-friendly '#xxxxxx' string.

    ReportLab's ``HexColor.hexval()`` returns ``'0x1a1f3a'`` (Python-literal
    style), which matplotlib rejects — we explicitly normalize to ``#xxxxxx``.
    """
    if hasattr(color, "hexval"):
        raw = color.hexval()  # '0xRRGGBB'
        if isinstance(raw, str) and raw.startswith("0x"):
            return "#" + raw[2:]
        return raw
    if hasattr(color, "rgb"):
        r, g, b = (int(c * 255) for c in color.rgb())
        return f"#{r:02x}{g:02x}{b:02x}"
    return str(color)
