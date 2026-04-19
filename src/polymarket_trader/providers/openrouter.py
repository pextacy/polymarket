from __future__ import annotations

from .openai_compatible import OpenAICompatibleProvider


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        api_key: str,
        base_url: str = "https://openrouter.ai/api/v1",
        default_model: str = "openai/gpt-4o",
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            default_model=default_model,
            default_headers={
                "HTTP-Referer": "https://github.com/polymarket-trader",
                "X-Title": "Polymarket Autonomous Trader",
            },
        )
