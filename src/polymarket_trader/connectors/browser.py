from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

import httpx
from loguru import logger

ALLOWED_SCHEMES = {"http", "https"}
BLOCKED_DOMAINS: set[str] = set()


class LightpandaClient:
    def __init__(
        self,
        ws_url: str,
        timeout: float = 30.0,
        max_page_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self._ws_url = ws_url
        self._timeout = timeout
        self._max_page_bytes = max_page_bytes
        self._http = httpx.AsyncClient(timeout=timeout)
        self._cdp_base = ws_url.replace("ws://", "http://").replace("wss://", "https://")

    async def __aenter__(self) -> LightpandaClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self._http.aclose()

    def _is_allowed(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
        except Exception:
            return False
        if parsed.scheme not in ALLOWED_SCHEMES:
            return False
        if parsed.netloc in BLOCKED_DOMAINS:
            return False
        return True

    async def fetch_text(self, url: str) -> Optional[str]:
        if not self._is_allowed(url):
            logger.warning("Browser: blocked URL {}", url)
            return None

        try:
            resp = await self._http.get(
                f"{self._cdp_base}/fetch",
                params={"url": url},
                timeout=self._timeout,
            )
            if resp.status_code == 200:
                data = resp.json()
                text: str = data.get("text", "")
                if len(text.encode()) > self._max_page_bytes:
                    text = text[: self._max_page_bytes]
                return text.strip() or None
        except Exception as e:
            logger.debug("Browser fetch failed for {}: {}", url, e)

        # Fallback: plain httpx fetch without JS rendering
        try:
            r = await self._http.get(url, timeout=self._timeout, follow_redirects=True)
            r.raise_for_status()
            text = r.text
            if len(text.encode()) > self._max_page_bytes:
                text = text[: self._max_page_bytes]
            return text.strip() or None
        except Exception as e:
            logger.debug("Browser fallback failed for {}: {}", url, e)
            return None
