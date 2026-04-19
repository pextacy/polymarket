from __future__ import annotations

from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models.market import MarketSnapshot


class OrderBookLevel(dict):
    pass


class ClobClient:
    def __init__(self, base_url: str, timeout: float = 15.0) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def __aenter__(self) -> ClobClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=15),
        reraise=True,
    )
    async def _get(self, path: str, params: dict | None = None) -> Any:
        response = await self._client.get(path, params=params)
        response.raise_for_status()
        return response.json()

    async def enrich_market(self, snapshot: MarketSnapshot) -> MarketSnapshot:
        if not snapshot.tokens:
            return snapshot

        yes_token = snapshot.yes_token
        if yes_token is None:
            return snapshot

        token_id = yes_token.token_id
        try:
            book_data = await self._get("/book", params={"token_id": token_id})
            bids: list[dict] = book_data.get("bids", [])
            asks: list[dict] = book_data.get("asks", [])

            best_bid = float(bids[0]["price"]) if bids else 0.0
            best_ask = float(asks[0]["price"]) if asks else 1.0
            spread = round(best_ask - best_bid, 6)

            snapshot.best_bid = best_bid
            snapshot.best_ask = best_ask
            snapshot.spread = spread
        except Exception as e:
            logger.debug("CLOB orderbook unavailable for {}: {}", token_id, e)

        try:
            market_data = await self._get(f"/markets/{snapshot.condition_id}")
            tick_size = float(market_data.get("minimum_tick_size", 0.01))
            min_size = float(market_data.get("minimum_order_size", 1.0))
            snapshot.tick_size = tick_size
            snapshot.min_order_size = min_size
        except Exception as e:
            logger.debug("CLOB market data unavailable for {}: {}", snapshot.condition_id, e)

        return snapshot

    async def get_midpoint(self, token_id: str) -> Optional[float]:
        try:
            data = await self._get("/midpoint", params={"token_id": token_id})
            return float(data.get("mid", 0))
        except Exception:
            return None

    async def get_price(self, token_id: str, side: str) -> Optional[float]:
        try:
            data = await self._get("/price", params={"token_id": token_id, "side": side})
            return float(data.get("price", 0))
        except Exception:
            return None

    async def check_geoblock(self) -> bool:
        try:
            response = await self._client.get("/geo-blocked")
            data = response.json()
            return bool(data.get("blocked", True))
        except Exception as e:
            logger.warning("Geoblock check failed: {} — assuming blocked", e)
            return True
