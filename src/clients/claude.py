"""Anthropic Claude API wrapper.

Системные промпты для типовых задач прописаны константами в этом же файле —
менять их можно прицельно, без проб по всему коду. Все методы возвращают
plain ``str`` (или кортежи примитивов) — это упрощает тестирование.
"""

from __future__ import annotations

import json
from typing import Final

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.utils.logger import get_logger


class ClaudeError(RuntimeError):
    """Wraps anthropic SDK errors with a readable message."""


SYSTEM_SCORE_IMPORTANCE: Final = """
You are a financial analyst evaluating news importance for an investor's portfolio.
Score each piece of news from 1 to 10 where:
- 1-3: Routine news, market noise.
- 4-6: Notable but not critical.
- 7-8: Important, requires attention.
- 9-10: Critical, immediate review needed.

Consider: regulatory impact, earnings implications, management changes,
litigation, M&A, macroeconomic relevance.

Return ONLY valid JSON, no prose: {"score": int, "reason": "brief explanation in Russian, 1 sentence"}
""".strip()

SYSTEM_DAILY_OBSERVATION: Final = """
You are a senior portfolio analyst writing a one-paragraph observation
for an investor's morning summary.

Style: factual, concise, no hype.
Length: strictly 1–2 sentences, max 280 characters.
Language: Russian.
Tone: informational, NOT advisory.

DO NOT give buy/sell recommendations, price predictions, or use words
like "лучший", "обязательно". Connect the day's movement to context
(SPY direction, VIX level, sector behavior) when possible.
""".strip()

SYSTEM_INSIGHTS: Final = """
You are a senior portfolio analyst writing the weekly insights section
for an investor's PDF report.

Style: professional, concise, factual. No hype. No buy/sell calls.
Language: Russian.
Tone: informational. Connect signals to portfolio impact.

Structure your answer as 2–4 short paragraphs. Each paragraph one idea.
""".strip()


class ClaudeClient:
    """Lightweight wrapper around ``anthropic.Anthropic``."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514") -> None:
        if not api_key:
            raise ClaudeError("Empty Claude API key")
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model
        self._logger = get_logger("claude")

    # ---------- Public API ----------

    def analyze(
        self,
        prompt: str,
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> str:
        """One-shot prompt → plain text reply."""
        return self._send_message(
            user_text=prompt,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
        )

    def score_importance(self, news_text: str, ticker: str) -> tuple[int, str]:
        """Return ``(score 1..10, short Russian explanation)`` for a news headline."""
        prompt = (
            f"Ticker: ${ticker}\n"
            f"News headline / snippet:\n{news_text}\n\n"
            "Return the JSON now."
        )
        raw = self._send_message(
            user_text=prompt,
            system=SYSTEM_SCORE_IMPORTANCE,
            max_tokens=256,
            temperature=0.0,
        )
        return _parse_score_json(raw)

    def generate_insights(
        self,
        portfolio_data: dict,
        signals: list,
        style: str = "professional",
    ) -> str:
        """Generate a structured insights blob for the weekly PDF."""
        payload = {
            "style": style,
            "portfolio": portfolio_data,
            "signals_summary": [
                {
                    "type": getattr(s, "signal_type", ""),
                    "ticker": getattr(s, "ticker", ""),
                    "severity": getattr(s, "severity", ""),
                    "title": getattr(s, "title", ""),
                }
                for s in signals
            ],
        }
        prompt = (
            "Below is portfolio data and a summary of signals fired this week. "
            "Write the insights section (2-4 paragraphs, Russian) for the report.\n\n"
            f"```json\n{json.dumps(payload, ensure_ascii=False, default=str)}\n```"
        )
        return self._send_message(
            user_text=prompt,
            system=SYSTEM_INSIGHTS,
            max_tokens=1200,
            temperature=0.3,
        )

    def generate_summary(self, market_data: dict, portfolio_change: dict) -> str:
        """One-paragraph (1-2 sentences) morning observation, Russian."""
        prompt = (
            "Market overnight:\n"
            f"```json\n{json.dumps(market_data, ensure_ascii=False, default=str)}\n```\n\n"
            "Portfolio change since prior close:\n"
            f"```json\n{json.dumps(portfolio_change, ensure_ascii=False, default=str)}\n```\n\n"
            "Write the observation now."
        )
        return self._send_message(
            user_text=prompt,
            system=SYSTEM_DAILY_OBSERVATION,
            max_tokens=300,
            temperature=0.4,
        )

    # ---------- Internals ----------

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        retry=retry_if_exception_type(
            (anthropic.APIConnectionError, anthropic.RateLimitError, anthropic.InternalServerError)
        ),
        reraise=True,
    )
    def _send_message(
        self,
        user_text: str,
        system: str | None,
        max_tokens: int,
        temperature: float,
    ) -> str:
        try:
            kwargs: dict = {
                "model": self._model,
                "max_tokens": max_tokens,
                "temperature": temperature,
                "messages": [{"role": "user", "content": user_text}],
            }
            if system:
                kwargs["system"] = system
            response = self._client.messages.create(**kwargs)
        except anthropic.AuthenticationError as exc:
            raise ClaudeError(
                "Claude API ключ невалиден (HTTP 401). "
                "Проверь CLAUDE_API_KEY в .env или GitHub Secrets."
            ) from exc
        except anthropic.PermissionDeniedError as exc:
            raise ClaudeError("Claude API: нет доступа к модели.") from exc
        except anthropic.BadRequestError as exc:
            raise ClaudeError(f"Claude API: некорректный запрос: {exc}") from exc

        text_chunks: list[str] = []
        for block in response.content:
            # anthropic SDK ≥0.39 — у блоков есть .type и .text
            if getattr(block, "type", "text") == "text":
                text_chunks.append(getattr(block, "text", ""))
        result = "".join(text_chunks).strip()
        self._logger.debug(
            "Claude reply (model=%s, in≈%d, out≈%d)",
            self._model,
            response.usage.input_tokens if response.usage else -1,
            response.usage.output_tokens if response.usage else -1,
        )
        return result


# ---------- Helpers ----------


def _parse_score_json(raw: str) -> tuple[int, str]:
    """Tolerant parser for the JSON returned by ``score_importance``."""
    text = raw.strip()
    # Иногда модель оборачивает в ```json … ``` — выкусим первую {…}.
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return 5, raw[:200]
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return 5, raw[:200]

    score = obj.get("score", 5)
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = 5
    score = max(1, min(10, score))
    reason = str(obj.get("reason", "")).strip() or "—"
    return score, reason
