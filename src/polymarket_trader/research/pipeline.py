from __future__ import annotations

import asyncio
import hashlib
from typing import Optional

from loguru import logger
from pydantic import BaseModel, Field

from ..connectors.browser import LightpandaClient
from ..connectors.search import SearXNGClient
from ..models.market import MarketSnapshot
from ..models.research import EvidenceItem
from ..providers.openrouter import OpenRouterProvider


class _QueriesOut(BaseModel):
    queries: list[str] = Field(..., min_length=1, max_length=5)


_QUERY_SYSTEM = """You are a research assistant for a prediction market trader. Generate 3 focused search queries to find reliable, recent evidence about the outcome of this market.

Each query should target a different angle (news, official sources, expert analysis).
Return ONLY valid JSON — no prose, no markdown."""


class ResearchPipeline:
    def __init__(
        self,
        search: SearXNGClient,
        browser: Optional[LightpandaClient],
        provider: OpenRouterProvider,
        extraction_model: Optional[str] = None,
        max_sources: int = 5,
    ) -> None:
        self._search = search
        self._browser = browser
        self._provider = provider
        self._extraction_model = extraction_model
        self._max_sources = max_sources

    async def research(self, market: MarketSnapshot) -> list[EvidenceItem]:
        queries = await self._generate_queries(market)
        if not queries:
            queries = [market.question]

        tasks = [self._search.search(q, max_results=self._max_sources) for q in queries]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        all_items: list[EvidenceItem] = []
        for batch in results:
            if isinstance(batch, Exception):
                logger.warning("Search batch failed: {}", batch)
                continue
            all_items.extend(batch)

        deduped = self._deduplicate(all_items)
        ranked = sorted(deduped, key=lambda e: e.score, reverse=True)
        top = ranked[: self._max_sources * 2]

        if self._browser is not None:
            top = await self._enrich_with_browser(top)

        fresh = [e for e in top if e.is_fresh(max_age_hours=168)]
        logger.info(
            "Research for '{}': {} items ({} fresh)",
            market.question[:60],
            len(top),
            len(fresh),
        )
        return fresh[: self._max_sources * 3]

    async def _generate_queries(self, market: MarketSnapshot) -> list[str]:
        try:
            result = await self._provider.complete_json(
                system=_QUERY_SYSTEM,
                user=f"Market question: {market.question}\nCategory: {market.category}",
                schema=_QueriesOut,
                model=self._extraction_model,
                temperature=0.3,
                max_tokens=256,
            )
            return result.queries[:3]
        except Exception as e:
            logger.warning("Query generation failed: {} — using question directly", e)
            return [market.question]

    async def _enrich_with_browser(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        fetch_tasks = [self._browser.fetch_text(item.url) for item in items]
        fetch_results = await asyncio.gather(*fetch_tasks, return_exceptions=True)

        enriched: list[EvidenceItem] = []
        for item, result in zip(items, fetch_results):
            if isinstance(result, Exception) or result is None:
                enriched.append(item)
            else:
                enriched.append(item.model_copy(update={"full_text": result[:4000]}))
        return enriched

    def _deduplicate(self, items: list[EvidenceItem]) -> list[EvidenceItem]:
        seen_urls: set[str] = set()
        seen_hashes: set[str] = set()
        result: list[EvidenceItem] = []

        for item in items:
            if item.url in seen_urls:
                continue
            snippet_hash = hashlib.md5(item.snippet[:100].encode()).hexdigest()
            if snippet_hash in seen_hashes:
                continue
            seen_urls.add(item.url)
            seen_hashes.add(snippet_hash)
            result.append(item)

        return result
