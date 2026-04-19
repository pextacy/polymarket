from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models.market import MarketSnapshot, TokenInfo


class GammaClient:
    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> GammaClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def fetch_active_markets(
        self,
        limit: int = 100,
        min_volume_24h: float = 0.0,
        min_liquidity: float = 0.0,
    ) -> list[MarketSnapshot]:
        offset = 0
        markets: list[MarketSnapshot] = []

        while True:
            params = {
                "active": "true",
                "closed": "false",
                "archived": "false",
                "limit": limit,
                "offset": offset,
            }
            try:
                data = await self._get("/markets", params=params)
            except httpx.HTTPStatusError as e:
                logger.error("Gamma API error fetching markets: {}", e)
                break

            batch = data if isinstance(data, list) else data.get("data", [])
            if not batch:
                break

            for raw in batch:
                snapshot = self._parse_market(raw)
                if snapshot is None:
                    continue
                if snapshot.volume_24h < min_volume_24h:
                    continue
                if snapshot.liquidity < min_liquidity:
                    continue
                markets.append(snapshot)

            if len(batch) < limit:
                break
            offset += limit

        logger.info("Gamma: fetched {} active markets", len(markets))
        return markets

    async def fetch_resolved_markets(
        self,
        days_back: int = 30,
        min_volume: float = 1000.0,
        limit: int = 200,
    ) -> list[MarketSnapshot]:
        """Fetch recently closed and resolved markets that have a clear winner token."""
        cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
        page_size = 100
        offset = 0
        markets: list[MarketSnapshot] = []

        while len(markets) < limit:
            params = {
                "closed": "true",
                "archived": "false",
                "limit": page_size,
                "offset": offset,
            }
            try:
                data = await self._get("/markets", params=params)
            except Exception as e:
                logger.error("Gamma error fetching resolved markets: {}", e)
                break

            batch = data if isinstance(data, list) else data.get("data", [])
            if not batch:
                break

            for raw in batch:
                snapshot = self._parse_market(raw)
                if snapshot is None:
                    continue
                if snapshot.end_date is not None:
                    end_aware = (
                        snapshot.end_date
                        if snapshot.end_date.tzinfo is not None
                        else snapshot.end_date.replace(tzinfo=timezone.utc)
                    )
                    if end_aware < cutoff:
                        continue
                if snapshot.volume_24h < min_volume and snapshot.liquidity < min_volume:
                    continue
                if not any(t.winner for t in snapshot.tokens):
                    continue
                markets.append(snapshot)
                if len(markets) >= limit:
                    break

            if len(batch) < page_size:
                break
            offset += page_size

        logger.info(
            "Gamma: fetched {} resolved markets ({}d back, min_vol=${:.0f})",
            len(markets),
            days_back,
            min_volume,
        )
        return markets

    async def fetch_market(self, condition_id: str) -> Optional[MarketSnapshot]:
        try:
            raw = await self._get(f"/markets/{condition_id}")
        except httpx.HTTPStatusError as e:
            logger.error("Gamma API error fetching market {}: {}", condition_id, e)
            return None
        return self._parse_market(raw)

    def _parse_market(self, raw: dict) -> Optional[MarketSnapshot]:
        try:
            tokens: list[TokenInfo] = []
            for t in raw.get("tokens", []):
                tokens.append(
                    TokenInfo(
                        token_id=t.get("token_id", ""),
                        outcome=t.get("outcome", ""),
                        price=float(t.get("price", 0)),
                        winner=bool(t.get("winner", False)),
                    )
                )

            end_date: Optional[datetime] = None
            if raw.get("end_date_iso"):
                try:
                    end_date = datetime.fromisoformat(
                        raw["end_date_iso"].replace("Z", "+00:00")
                    )
                except ValueError:
                    pass

            return MarketSnapshot(
                condition_id=raw.get("condition_id", raw.get("conditionId", "")),
                question_id=raw.get("question_id", raw.get("questionId", "")),
                question=raw.get("question", ""),
                description=raw.get("description", ""),
                category=raw.get("category", "general"),
                slug=raw.get("slug", ""),
                resolution_source=raw.get("resolution_source", ""),
                end_date=end_date,
                active=bool(raw.get("active", True)),
                closed=bool(raw.get("closed", False)),
                archived=bool(raw.get("archived", False)),
                tokens=tokens,
                volume_24h=float(raw.get("volume24hr", raw.get("volume_24hr", 0))),
                liquidity=float(raw.get("liquidity", 0)),
            )
        except Exception as e:
            logger.warning("Failed to parse market {}: {}", raw.get("condition_id"), e)
            return None
