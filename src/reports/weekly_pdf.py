"""Weekly PDF report — премиум-уровень.

Каждая страница собирается в отдельный метод ``_build_<section>``, что
позволяет легко переставить их местами или временно отключить одну. Все
методы устойчивы к отсутствующим данным — возвращают placeholder, но не
падают.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from src.analytics.insights import InsightsGenerator
from src.analytics.performance import PerformanceAnalytics
from src.analytics.risk import RiskAnalytics
from src.constants import PATH_REPORTS_ARCHIVE
from src.reports.charts import ChartGenerator
from src.reports.pdf_templates import (
    _FONT_BOLD,
    _FONT_REGULAR,
    DISCLAIMER_TEXT,
    PDFTheme,
)
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
    from src.utils.dedup import SignalDeduplicator


class WeeklyReport:
    def __init__(
        self,
        config,
        market_client: MarketDataClient,
        claude_client: ClaudeClient,
        deduplicator: SignalDeduplicator | None = None,
    ) -> None:
        self.config = config
        self.market = market_client
        self.claude = claude_client
        self.deduplicator = deduplicator

        self.theme = PDFTheme(theme=config.pdf.theme, accent=config.pdf.accent_color)
        self.styles = self.theme.get_styles()
        self.charts = ChartGenerator(self.theme)
        self.risk = RiskAnalytics(market_client)
        self.performance = PerformanceAnalytics(market_client)
        self.insights = InsightsGenerator(claude_client)
        self.logger = get_logger("weekly_pdf")

    # ---------- Public ----------

    def generate(self, positions: list[Position]) -> str:
        data = self._prepare_data(positions)
        out_dir = Path(PATH_REPORTS_ARCHIVE)
        out_dir.mkdir(parents=True, exist_ok=True)
        filename = f"weekly_report_{datetime.now().strftime('%Y%m%d')}.pdf"
        pdf_path = out_dir / filename

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            leftMargin=2 * cm,
            rightMargin=2 * cm,
            topMargin=2 * cm,
            bottomMargin=2 * cm,
            title="Claude Portfolio Watchdog — Weekly Report",
            author="Claude Portfolio Watchdog",
        )

        story = []
        story.extend(self._build_cover_page(data))
        story.append(PageBreak())
        story.extend(self._build_executive_summary(data))
        story.append(PageBreak())
        story.extend(self._build_composition_page(data))
        story.append(PageBreak())
        story.extend(self._build_performance_page(data))
        story.append(PageBreak())
        story.extend(self._build_positions_review(data))
        story.append(PageBreak())
        story.extend(self._build_signals_page(data))
        story.append(PageBreak())
        story.extend(self._build_risk_page(data))
        story.append(PageBreak())
        story.extend(self._build_forward_page(data))
        story.append(PageBreak())
        story.extend(self._build_insights_page(data))
        story.append(PageBreak())
        story.extend(self._build_disclaimer_page())

        doc.build(
            story,
            onFirstPage=self._draw_page_chrome,
            onLaterPages=self._draw_page_chrome,
        )
        self.logger.info("Weekly PDF written to %s", pdf_path)
        return str(pdf_path)

    # ---------- Data prep ----------

    def _prepare_data(self, positions: list[Position]) -> dict:
        benchmark = self.config.reports.benchmark or "SPY"
        perf = self.performance.calculate_returns(positions, period="1w")
        bench = self.performance.compare_to_benchmark(positions, benchmark, "1w")
        movers = self.performance.get_top_movers(positions, "1w", n=3)

        portfolio_history = _portfolio_history(self.market, positions, period="1mo")
        bench_history = _close_series(self.market, benchmark, period="1mo")

        risk = {
            "beta": self.risk.calculate_beta(positions, benchmark, "1y"),
            "correlations": self.risk.calculate_correlations(positions, "3mo"),
            "max_drawdown": self.risk.calculate_max_drawdown(positions, "1y"),
            "var": self.risk.calculate_var(positions),
            "concentration": self.risk.calculate_concentration(positions),
        }

        signals_week = []
        if self.deduplicator is not None:
            signals_week = self.deduplicator.signals_in_window(days=7)

        return {
            "positions": positions,
            "performance": perf,
            "benchmark": bench,
            "movers": movers,
            "risk": risk,
            "signals_week": signals_week,
            "portfolio_history": portfolio_history,
            "benchmark_history": bench_history,
            "benchmark_ticker": benchmark,
        }

    # ---------- Sections ----------

    def _build_cover_page(self, data: dict) -> list:
        perf = data["performance"]
        title = Paragraph("CLAUDE PORTFOLIO<br/>WATCHDOG", self.styles["title"])
        subtitle = Paragraph(
            f"Weekly Report · {datetime.now().strftime('%d %B %Y')}",
            self.styles["subtitle"],
        )

        metric = self._metric_row(
            ("Portfolio value", format_currency(perf["total_end"], self.config.reports.currency)),
            ("Week change",
             f"{format_currency(perf['total_return_usd'])} ({format_percent(perf['total_return_percent'])})"),
            ("vs Benchmark", f"{format_percent(data['benchmark']['alpha'])} alpha"),
        )

        # Three "key insights" — берём из исходных движков, без Claude (быстро, без API).
        leaders = ", ".join(f"${t} {format_percent(p)}" for t, p in data["movers"]["leaders"]) or "—"
        laggards = ", ".join(f"${t} {format_percent(p)}" for t, p in data["movers"]["laggards"]) or "—"
        insights_block = [
            f"▲ Leaders this week: {leaders}",
            f"▼ Laggards: {laggards}",
            f"◆ Portfolio beta vs {data['benchmark_ticker']}: <b>{data['risk']['beta']:.2f}</b>",
        ]
        bullets = [Paragraph(b, self.styles["body"]) for b in insights_block]

        return [
            Spacer(1, 1.5 * cm),
            title,
            subtitle,
            Spacer(1, 0.5 * cm),
            metric,
            Spacer(1, 1.0 * cm),
            Paragraph("KEY INSIGHTS THIS WEEK", self.styles["h2"]),
            *bullets,
        ]

    def _build_executive_summary(self, data: dict) -> list:
        summary = self.insights.generate_executive_summary(
            portfolio_data={
                "tickers": [p.ticker for p in data["positions"]],
                "current_value": data["performance"]["total_end"],
                "week_change_pct": data["performance"]["total_return_percent"],
            },
            signals_week=[],
            performance=data["performance"],
            risk={"beta": data["risk"]["beta"], "drawdown": data["risk"]["max_drawdown"]},
        )
        return [
            Paragraph("Executive Summary", self.styles["h1"]),
            Spacer(1, 0.2 * cm),
            Paragraph(escape_html(summary), self.styles["body"]),
        ]

    def _build_composition_page(self, data: dict) -> list:
        story = [Paragraph("Portfolio Composition", self.styles["h1"])]
        story.append(Paragraph("By position", self.styles["h2"]))

        pie = self.charts.portfolio_composition_pie(data["positions"])
        story.append(Image(pie, width=15 * cm, height=10 * cm))

        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("By sector", self.styles["h2"]))
        sector_bar = self.charts.sector_distribution_bar(
            data["risk"]["concentration"].get("by_sector", {})
        )
        story.append(Image(sector_bar, width=15 * cm, height=8 * cm))

        # Top-3 concentration warning.
        concentration = data["risk"]["concentration"]
        top_share = concentration.get("top_3_share", 0.0) * 100
        if top_share >= 50:
            story.append(Spacer(1, 0.3 * cm))
            story.append(
                Paragraph(
                    f"⚠ Концентрация: топ-3 позиции — {top_share:.1f}% портфеля.",
                    self.styles["body_secondary"],
                )
            )
        return story

    def _build_performance_page(self, data: dict) -> list:
        story = [Paragraph("Performance Analysis", self.styles["h1"])]
        story.append(
            Paragraph(
                f"Performance vs benchmark ({data['benchmark_ticker']})",
                self.styles["h2"],
            )
        )
        story.append(
            Image(
                self.charts.portfolio_value_chart(
                    data["portfolio_history"],
                    data["benchmark_history"],
                    benchmark_label=f"{data['benchmark_ticker']}",
                ),
                width=16 * cm,
                height=8 * cm,
            )
        )
        story.append(Spacer(1, 0.4 * cm))
        story.append(Paragraph("Top movers (1w)", self.styles["h2"]))

        rows = [["#", "Leaders", "Return", "", "Laggards", "Return"]]
        leaders = data["movers"]["leaders"]
        laggards = data["movers"]["laggards"]
        for i in range(max(len(leaders), len(laggards))):
            lead = leaders[i] if i < len(leaders) else ("—", 0.0)
            lag = laggards[i] if i < len(laggards) else ("—", 0.0)
            rows.append(
                [
                    str(i + 1),
                    f"${lead[0]}",
                    format_percent(lead[1]),
                    "",
                    f"${lag[0]}",
                    format_percent(lag[1]),
                ]
            )
        table = Table(rows, colWidths=[1 * cm, 4 * cm, 3 * cm, 1 * cm, 4 * cm, 3 * cm])
        table.setStyle(self._table_style(header=True))
        story.append(table)
        return story

    def _build_positions_review(self, data: dict) -> list:
        story = [Paragraph("Position-by-Position Review", self.styles["h1"])]
        per_position = data["performance"]["by_position"]
        for pos in data["positions"][:8]:
            stats = per_position.get(pos.ticker, {})
            return_pct = stats.get("return_percent", 0.0)
            hist = _close_series(self.market, pos.ticker, period="1mo")
            mini = self.charts.position_mini_chart(pos.ticker, hist)

            secondary_hex = self.theme.text_secondary.hexval().replace("0x", "#")
            header = Paragraph(
                f"<b>${escape_html(pos.ticker)}</b> &nbsp; "
                f"<font color='{secondary_hex}'>"
                f"{escape_html(pos.company_name or '')}</font>",
                self.styles["body"],
            )
            metrics = Paragraph(
                f"Quantity: {pos.quantity:g} · Avg cost: {format_currency(pos.average_cost)} · "
                f"Market value: {format_currency(pos.market_value)} · "
                f"1w return: <b>{format_percent(return_pct)}</b>",
                self.styles["body_secondary"],
            )
            row_table = Table(
                [[header, Image(mini, width=8 * cm, height=2.4 * cm)]],
                colWidths=[8.5 * cm, 8.5 * cm],
            )
            row_table.setStyle(
                TableStyle(
                    [
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 0),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                    ]
                )
            )
            story.append(KeepTogether([row_table, metrics, Spacer(1, 0.3 * cm)]))
        return story

    def _build_signals_page(self, data: dict) -> list:
        story = [Paragraph("Signals Recap (last 7 days)", self.styles["h1"])]
        signals = data["signals_week"]
        if not signals:
            story.append(
                Paragraph("Сигналов за неделю не было.", self.styles["body_secondary"])
            )
            return story

        rows = [["Type", "Ticker", "Severity", "Title"]]
        for s in signals:
            rows.append(
                [
                    s.get("signal_type", "—"),
                    s.get("ticker", "—"),
                    s.get("severity", "—"),
                    s.get("title", "—")[:60],
                ]
            )
        table = Table(rows, colWidths=[3 * cm, 2 * cm, 2.5 * cm, 9 * cm])
        table.setStyle(self._table_style(header=True))
        story.append(table)
        return story

    def _build_risk_page(self, data: dict) -> list:
        risk = data["risk"]
        story = [Paragraph("Risk Analysis", self.styles["h1"])]
        story.append(Paragraph("Position correlation matrix", self.styles["h2"]))

        story.append(
            Image(
                self.charts.correlation_heatmap(risk["correlations"]),
                width=14 * cm, height=10 * cm,
            )
        )
        story.append(Spacer(1, 0.4 * cm))

        # Metrics row
        dd = risk["max_drawdown"]
        var = risk["var"]
        beta = risk["beta"]
        conc = risk["concentration"]
        rows = [
            ["Beta", f"{beta:.2f}"],
            ["Max drawdown", f"{dd.get('drawdown_percent', 0):.1f}% "
                              f"({dd.get('peak_date', '?')} → {dd.get('trough_date', '?')})"],
            ["Value at Risk (95%, 1d)", format_currency(var)],
            ["HHI concentration", f"{conc.get('hhi', 0):.3f}"],
            ["Top-3 share", format_percent(conc.get('top_3_share', 0) * 100, with_sign=False)],
        ]
        table = Table(rows, colWidths=[7 * cm, 9 * cm])
        table.setStyle(self._table_style(header=False))
        story.append(table)

        story.append(Spacer(1, 0.3 * cm))
        commentary = self.insights.generate_risk_commentary(
            risk_data={"beta": beta, "drawdown": dd, "var": var, "concentration": conc},
            portfolio_data={"tickers": [p.ticker for p in data["positions"]]},
        )
        story.append(Paragraph(escape_html(commentary), self.styles["body"]))
        return story

    def _build_forward_page(self, data: dict) -> list:
        story = [Paragraph("What's Ahead Next Week", self.styles["h1"])]
        # Earnings — берём из yfinance calendar.
        upcoming_earnings = []
        for pos in data["positions"][:15]:
            try:
                cal = self.market.get_earnings_calendar(pos.ticker)
            except Exception:
                continue
            dates = cal.get("Earnings Date") if isinstance(cal, dict) else None
            first = dates[0] if isinstance(dates, list) and dates else None
            if first is not None:
                upcoming_earnings.append({"ticker": pos.ticker, "date": str(first)[:10]})

        if upcoming_earnings:
            story.append(Paragraph("Upcoming earnings", self.styles["h2"]))
            for entry in upcoming_earnings:
                story.append(
                    Paragraph(
                        f"• ${entry['ticker']} — {entry['date']}",
                        self.styles["body_secondary"],
                    )
                )
        else:
            story.append(
                Paragraph("Earnings на ближайшие 7 дней не найдены.", self.styles["body_secondary"])
            )

        outlook = self.insights.generate_forward_outlook(
            upcoming_earnings=upcoming_earnings,
            upcoming_macro=[],  # MacroMonitor сам формирует сигналы — здесь не дублируем.
            portfolio_data={"tickers": [p.ticker for p in data["positions"]]},
        )
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(escape_html(outlook), self.styles["body"]))
        return story

    def _build_insights_page(self, data: dict) -> list:
        story = [Paragraph("Claude Insights", self.styles["h1"])]
        recommendations = self.insights.generate_recommendations(
            portfolio_data={"tickers": [p.ticker for p in data["positions"]]},
            all_data={
                "performance": data["performance"],
                "risk_summary": {
                    "beta": data["risk"]["beta"],
                    "drawdown": data["risk"]["max_drawdown"],
                },
            },
        )
        if not recommendations:
            recommendations = ["Существенных событий не обнаружено."]
        for rec in recommendations:
            story.append(Paragraph(f"• {escape_html(rec)}", self.styles["body"]))
        return story

    def _build_disclaimer_page(self) -> list:
        return [
            Spacer(1, 8 * cm),
            Paragraph(DISCLAIMER_TEXT, self.styles["disclaimer"]),
        ]

    # ---------- Helpers ----------

    def _metric_row(self, *items: tuple[str, str]) -> Table:
        # Each item rendered as a small "card".
        cells = []
        for label, value in items:
            cells.append(
                [
                    Paragraph(label, self.styles["metric_label"]),
                    Paragraph(value, self.styles["metric_value"]),
                ]
            )

        inner_tables = []
        for label_para, value_para in cells:
            inner = Table([[value_para], [label_para]], colWidths=[5.6 * cm])
            inner.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, -1), self.theme.bg_secondary),
                        ("BOX", (0, 0), (-1, -1), 0.6, self.theme.divider),
                        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 8),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                        ("TOPPADDING", (0, 0), (-1, -1), 14),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
                    ]
                )
            )
            inner_tables.append(inner)

        outer = Table([inner_tables], colWidths=[5.8 * cm] * len(inner_tables))
        outer.setStyle(
            TableStyle(
                [
                    ("LEFTPADDING", (0, 0), (-1, -1), 0),
                    ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ]
            )
        )
        return outer

    def _table_style(self, header: bool) -> TableStyle:
        cmds = [
            ("FONTNAME", (0, 0), (-1, -1), _FONT_REGULAR),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("TEXTCOLOR", (0, 0), (-1, -1), self.theme.text_primary),
            ("BACKGROUND", (0, 0), (-1, -1), self.theme.bg_secondary),
            ("LINEBELOW", (0, 0), (-1, -1), 0.3, self.theme.divider),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]
        if header:
            cmds.extend(
                [
                    ("FONTNAME", (0, 0), (-1, 0), _FONT_BOLD),
                    ("TEXTCOLOR", (0, 0), (-1, 0), self.theme.accent),
                    ("BACKGROUND", (0, 0), (-1, 0), self.theme.bg_primary),
                ]
            )
        return TableStyle(cmds)

    def _draw_page_chrome(self, canvas, doc) -> None:
        canvas.saveState()
        canvas.setFillColor(self.theme.bg_primary)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        # Footer.
        canvas.setFillColor(self.theme.text_secondary)
        canvas.setFont(_FONT_REGULAR, 8)
        canvas.drawString(2 * cm, 1 * cm, f"Claude Portfolio Watchdog · Page {doc.page}")
        canvas.drawRightString(
            A4[0] - 2 * cm, 1 * cm,
            datetime.now().strftime("%d %B %Y"),
        )
        canvas.restoreState()


# ---------- Module-level helpers ----------


def _close_series(market_client, ticker: str, period: str = "1mo") -> pd.Series:
    hist = market_client.get_price_history(ticker, period=period, interval="1d")
    if hist is None or hist.empty or "Close" not in hist.columns:
        return pd.Series(dtype=float)
    return hist["Close"].dropna()


def _portfolio_history(market_client, positions, period: str = "1mo") -> pd.Series:
    frames = []
    for pos in positions:
        closes = _close_series(market_client, pos.ticker, period=period)
        if closes.empty:
            continue
        qty = pos.quantity or 0
        if qty == 0:
            # Fallback-режим без CSV: всё равно покажем "форму" движения через
            # нормализованный close (полезно для cover-page графика).
            qty = 1
        frames.append((closes * qty).rename(pos.ticker))
    if not frames:
        return pd.Series(dtype=float)
    joined = pd.concat(frames, axis=1).ffill().fillna(0.0)
    return joined.sum(axis=1)
