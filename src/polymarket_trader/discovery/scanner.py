from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from ..config import Settings
from ..connectors.clob import ClobClient
from ..connectors.gamma import GammaClient
from ..intelligence.ranker import Ranker
from ..models.market import MarketSnapshot


class MarketScanner:
    def __init__(
        self,
        gamma: GammaClient,
        clob: ClobClient,
        ranker: Ranker,
        settings: Settings,
    ) -> None:
        self._gamma = gamma
        self._clob = clob
        self._ranker = ranker
        self._settings = settings

    async def scan(self, top_n: int = 20) -> list[MarketSnapshot]:
        markets = await self._gamma.fetch_active_markets(
            limit=self._settings.scan_market_limit,
            min_volume_24h=self._settings.scan_min_volume_24h_usdc,
            min_liquidity=self._settings.scan_min_liquidity_usdc,
        )

        if not markets:
            logger.warning("No markets returned from Gamma API")
            return []

        logger.info("Scanner: {} markets after initial filters", len(markets))

        ranked = await self._ranker.rank(markets, top_n=top_n)
        enriched = await self._enrich_with_clob(ranked)

        logger.info("Scanner: {} markets enriched with CLOB data", len(enriched))
        return enriched

    async def _enrich_with_clob(
        self, markets: list[MarketSnapshot]
    ) -> list[MarketSnapshot]:
        sem = asyncio.Semaphore(5)

        async def _enrich_one(m: MarketSnapshot) -> MarketSnapshot:
            async with sem:
                try:
                    return await self._clob.enrich_market(m)
                except Exception as e:
                    logger.debug("CLOB enrich failed for {}: {}", m.condition_id, e)
                    return m

        results = await asyncio.gather(*[_enrich_one(m) for m in markets])
        return list(results)
