"""Claude-powered insights generator used by daily summary + weekly PDF."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from src.clients.claude import ClaudeClient
    from src.monitors.base import Signal
    from src.portfolio_loader import Position


_ANTI_HALLUCINATION = (
    "CRITICAL: Use ONLY numeric values that appear in the JSON data provided "
    "to you in the user message. Do NOT invent percentages, prices, beta values, "
    "drawdown numbers, or any other statistics. If a number is needed but not "
    "given — describe qualitatively (\"умеренная концентрация\") instead of "
    "fabricating a number. Never reference cash amounts, percentages, or "
    "portfolio sizes that contradict the provided data."
)

SYSTEM_EXEC_SUMMARY = f"""
You are a senior portfolio analyst writing the executive summary for a weekly
investor report.

Style: professional, concise, factual.
Length: 3-5 sentences.
Language: Russian.
Tone: informational, not advisory.

DO NOT give buy/sell recommendations, price predictions, or use hype language.
DO highlight notable changes, explain context, note risks worth monitoring,
and connect signals to portfolio impact.

{_ANTI_HALLUCINATION}
""".strip()

SYSTEM_POSITION = f"""
You are writing a one-paragraph commentary for a single portfolio position,
to be embedded into a weekly PDF report.

Style: professional, concrete, in Russian. 3-5 sentences max.
Reference price action, signals, and material context. No advice.

{_ANTI_HALLUCINATION}
""".strip()

SYSTEM_RISK = f"""
You are writing a 2-3 paragraph risk commentary for a portfolio. Russian, professional.
Cover: beta, top correlations, drawdown context, concentration concerns.

{_ANTI_HALLUCINATION}
""".strip()

SYSTEM_OUTLOOK = f"""
You are writing the 'forward week' section of a weekly investor report.
Russian, 2-3 paragraphs. Connect upcoming earnings and macro events to portfolio impact.
No predictions about price direction. Highlight what to monitor.

{_ANTI_HALLUCINATION}
""".strip()

SYSTEM_RECOMMENDATIONS = """
You are writing a short bullet list (3-5 items) of things the investor should check
this week — risks, positions worth attention, upcoming events. Russian, neutral tone.
Start each line with a verb. No buy/sell calls.
Return one bullet per line, prefixed with '• '.
""".strip()

SYSTEM_DAILY = f"""
You are writing a one-paragraph (1-2 sentences) morning observation in Russian
for an investor's daily summary. Factual, no hype, no predictions.

{_ANTI_HALLUCINATION}
""".strip()


class InsightsGenerator:
    def __init__(self, claude_client: ClaudeClient) -> None:
        self.claude = claude_client
        self._logger = get_logger("insights")

    # ---------- Public API ----------

    def generate_executive_summary(
        self,
        portfolio_data: dict,
        signals_week: list[Signal],
        performance: dict,
        risk: dict,
    ) -> str:
        prompt = (
            "Portfolio snapshot:\n"
            f"```json\n{_json(portfolio_data)}\n```\n\n"
            "Performance:\n"
            f"```json\n{_json(performance)}\n```\n\n"
            "Risk metrics:\n"
            f"```json\n{_json(risk)}\n```\n\n"
            f"Signals fired this week (count={len(signals_week)}):\n"
            f"```json\n{_json(_signal_digest(signals_week))}\n```\n\n"
            "Write the executive summary now."
        )
        return self._safe_analyze(prompt, SYSTEM_EXEC_SUMMARY, max_tokens=600)

    def generate_position_analysis(
        self, position: Position, market_data: dict, signals: list[Signal]
    ) -> str:
        prompt = (
            f"Ticker: ${position.ticker}\n"
            f"Quantity: {position.quantity}\n"
            f"Avg cost: ${position.average_cost:.2f}\n"
            f"Current value: ${position.market_value:.2f}\n"
            f"Market context: {_json(market_data)}\n"
            f"Signals this week: {_json(_signal_digest(signals))}\n\n"
            "Write the commentary now."
        )
        return self._safe_analyze(prompt, SYSTEM_POSITION, max_tokens=350)

    def generate_risk_commentary(self, risk_data: dict, portfolio_data: dict) -> str:
        prompt = (
            "Risk metrics:\n"
            f"```json\n{_json(risk_data)}\n```\n\n"
            "Portfolio data:\n"
            f"```json\n{_json(portfolio_data)}\n```\n\n"
            "Write the risk commentary now."
        )
        return self._safe_analyze(prompt, SYSTEM_RISK, max_tokens=600)

    def generate_forward_outlook(
        self,
        upcoming_earnings: list[dict],
        upcoming_macro: list[dict],
        portfolio_data: dict,
    ) -> str:
        prompt = (
            "Upcoming earnings:\n"
            f"```json\n{_json(upcoming_earnings)}\n```\n\n"
            "Upcoming macro events:\n"
            f"```json\n{_json(upcoming_macro)}\n```\n\n"
            "Portfolio data:\n"
            f"```json\n{_json(portfolio_data)}\n```\n\n"
            "Write the forward outlook now."
        )
        return self._safe_analyze(prompt, SYSTEM_OUTLOOK, max_tokens=500)

    def generate_recommendations(self, portfolio_data: dict, all_data: dict) -> list[str]:
        prompt = (
            "Portfolio + all aggregated data:\n"
            f"```json\n{_json({'portfolio': portfolio_data, 'data': all_data})}\n```\n\n"
            "Write the bullet list now."
        )
        text = self._safe_analyze(prompt, SYSTEM_RECOMMENDATIONS, max_tokens=300)
        bullets = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            # Принимаем все варианты bullet'ов.
            for prefix in ("• ", "- ", "* ", "— "):
                if line.startswith(prefix):
                    line = line[len(prefix):]
                    break
            bullets.append(line)
        return bullets[:6]

    def generate_daily_observation(
        self,
        portfolio_change: dict,
        market_context: dict,
        signals_today: list[Signal],
    ) -> str:
        prompt = (
            f"Portfolio change:\n```json\n{_json(portfolio_change)}\n```\n\n"
            f"Market context:\n```json\n{_json(market_context)}\n```\n\n"
            f"Signals today:\n```json\n{_json(_signal_digest(signals_today))}\n```\n\n"
            "Write the observation now."
        )
        return self._safe_analyze(prompt, SYSTEM_DAILY, max_tokens=200)

    # ---------- Internals ----------

    def _safe_analyze(self, prompt: str, system: str, max_tokens: int) -> str:
        try:
            return self.claude.analyze(prompt, system=system, max_tokens=max_tokens)
        except Exception as exc:
            self._logger.warning("Claude insight failed: %s", exc)
            return "—"


def _json(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)[:4000]


def _signal_digest(signals: list[Signal]) -> list[dict]:
    return [
        {
            "type": s.signal_type,
            "ticker": s.ticker,
            "severity": s.severity,
            "title": s.title,
        }
        for s in signals
    ]
