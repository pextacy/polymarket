from __future__ import annotations

from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from ..models.market import MarketSnapshot
from ..providers.openrouter import OpenRouterProvider


class _RankOut(BaseModel):
    ranked: list[str] = Field(default_factory=list)


_SYSTEM = """You are a prediction market researcher. Given a list of markets, rank them by how likely you can find reliable public evidence to assess the outcome.

Prefer markets that:
- have factual, verifiable outcomes
- are about well-documented events (elections, sports, economics, science)
- resolve soon (within days or weeks)

Deprioritize:
- subjective or opinion markets
- markets about niche or obscure events with little public information
- markets resolving very far in the future

Return ONLY valid JSON with a "ranked" array of condition_ids in descending priority order."""


class Ranker:
    def __init__(
        self,
        provider: OpenRouterProvider,
        model: Optional[str] = None,
    ) -> None:
        self._provider = provider
        self._model = model

    async def rank(
        self,
        markets: list[MarketSnapshot],
        top_n: int = 20,
    ) -> list[MarketSnapshot]:
        if not markets:
            return []

        if len(markets) <= top_n:
            return markets

        market_list = "\n".join(
            f"- condition_id: {m.condition_id} | question: {m.question[:120]} | "
            f"end_date: {m.end_date.date() if m.end_date else 'unknown'} | "
            f"volume_24h: ${m.volume_24h:.0f} | liquidity: ${m.liquidity:.0f}"
            for m in markets[:50]
        )

        try:
            result = await self._provider.complete_json(
                system=_SYSTEM,
                user=f"Rank these markets by researchability:\n\n{market_list}\n\nReturn top {top_n}.",
                schema=_RankOut,
                model=self._model,
                temperature=0.1,
                max_tokens=1024,
            )
            ranked_ids = result.ranked[:top_n]

            id_to_market = {m.condition_id: m for m in markets}
            ranked: list[MarketSnapshot] = []
            for cid in ranked_ids:
                if cid in id_to_market:
                    ranked.append(id_to_market[cid])

            seen = {m.condition_id for m in ranked}
            for m in markets:
                if m.condition_id not in seen:
                    ranked.append(m)
                if len(ranked) >= top_n:
                    break

            return ranked

        except Exception as e:
            logger.warning("Ranker failed: {} — using volume sort fallback", e)
            return sorted(markets, key=lambda m: m.volume_24h, reverse=True)[:top_n]
