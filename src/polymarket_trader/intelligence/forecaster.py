from __future__ import annotations

from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field, field_validator

from ..models.forecast import Forecast, OutcomeProbability
from ..models.market import MarketSnapshot
from ..models.research import EvidenceItem
from ..providers.openrouter import OpenRouterProvider


class _OutcomeOut(BaseModel):
    outcome: str
    fair_probability: float = Field(..., ge=0.0, le=1.0)


class _ForecastOut(BaseModel):
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    outcomes: list[_OutcomeOut] = Field(..., min_length=1)

    @field_validator("outcomes")
    @classmethod
    def probabilities_sum_to_one(cls, v: list[_OutcomeOut]) -> list[_OutcomeOut]:
        total = sum(o.fair_probability for o in v)
        if total <= 0:
            raise ValueError("outcome probabilities must sum to > 0")
        # normalise to exactly 1.0
        for o in v:
            o.fair_probability = round(o.fair_probability / total, 6)
        return v


_SYSTEM = """You are a professional prediction market analyst. Estimate fair probabilities for the given Polymarket market.

Rules:
- Base your assessment strictly on the provided evidence
- Probabilities for all outcomes must sum to 1.0
- confidence reflects how certain you are given available evidence (0=no idea, 1=certain)
- For binary markets, YES + NO probabilities must equal exactly 1.0
- Output ONLY valid JSON — no prose, no markdown"""


class Forecaster:
    def __init__(
        self,
        provider: OpenRouterProvider,
        model: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._model = model

    async def forecast(
        self,
        market: MarketSnapshot,
        evidence: list[EvidenceItem],
    ) -> Optional[Forecast]:
        if not market.tokens:
            logger.warning("No tokens for market {}", market.condition_id)
            return None

        evidence_text = self._format_evidence(evidence)
        outcomes_text = "\n".join(
            f"- {t.outcome} (current market price: {t.price:.3f})"
            for t in market.tokens
        )

        user_prompt = (
            f"Market question: {market.question}\n"
            f"Resolution source: {market.resolution_source or 'Unknown'}\n"
            f"End date: {market.end_date.isoformat() if market.end_date else 'Unknown'}\n\n"
            f"Outcomes:\n{outcomes_text}\n\n"
            f"Evidence ({len(evidence)} sources):\n{evidence_text}\n\n"
            "Estimate the fair probability for each outcome."
        )

        try:
            result = await self._provider.complete_json(
                system=_SYSTEM,
                user=user_prompt,
                schema=_ForecastOut,
                model=self._model,
                temperature=0.1,
                max_tokens=1024,
            )
        except Exception as e:
            logger.error("Forecast failed for {}: {}", market.condition_id, e)
            return None

        token_by_outcome = {t.outcome.lower(): t for t in market.tokens}
        outcome_probs: list[OutcomeProbability] = []

        for o in result.outcomes:
            token = token_by_outcome.get(o.outcome.lower())
            if token is None:
                token = market.tokens[0]
            outcome_probs.append(
                OutcomeProbability(
                    outcome=o.outcome,
                    token_id=token.token_id,
                    fair_probability=o.fair_probability,
                    market_price=token.price,
                )
            )

        return Forecast(
            condition_id=market.condition_id,
            confidence=result.confidence,
            rationale=result.rationale,
            sources_used=[e.url for e in evidence],
            outcomes=outcome_probs,
            model_used=self._model or "default",
        )

    def _format_evidence(self, evidence: list[EvidenceItem]) -> str:
        if not evidence:
            return "No evidence available."
        parts = []
        for i, item in enumerate(evidence[:10], 1):
            date_str = (
                item.published_at.strftime("%Y-%m-%d") if item.published_at else "unknown date"
            )
            parts.append(
                f"[{i}] {item.title} ({item.source}, {date_str})\n{item.snippet[:400]}"
            )
        return "\n\n".join(parts)
