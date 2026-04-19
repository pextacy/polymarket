from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

import httpx
from loguru import logger
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models.research import EvidenceItem


class SearXNGClient:
    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
    ) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> SearXNGClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=20),
        reraise=True,
    )
    async def search(
        self,
        query: str,
        max_results: int = 10,
        engines: Optional[list[str]] = None,
    ) -> list[EvidenceItem]:
        params: dict[str, Any] = {
            "q": query,
            "format": "json",
            "pageno": 1,
        }
        if engines:
            params["engines"] = ",".join(engines)

        try:
            response = await self._client.get("/search", params=params)
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as e:
            logger.error("SearXNG search error for '{}': {}", query, e)
            return []
        except Exception as e:
            logger.error("SearXNG unreachable: {}", e)
            return []

        results: list[EvidenceItem] = []
        for i, raw in enumerate(data.get("results", [])[:max_results]):
            published_at = self._parse_published(raw.get("publishedDate"))
            item = EvidenceItem(
                title=raw.get("title", ""),
                url=raw.get("url", ""),
                snippet=raw.get("content", ""),
                source=raw.get("engine", raw.get("parsed_url", [None, None])[1] or ""),
                published_at=published_at,
                score=float(raw.get("score", max_results - i)),
            )
            results.append(item)

        logger.debug("SearXNG: '{}' → {} results", query, len(results))
        return results

    def _parse_published(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d", "%B %d, %Y"):
            try:
                return datetime.strptime(value[:len(fmt)], fmt)
            except (ValueError, TypeError):
                continue
        return None
