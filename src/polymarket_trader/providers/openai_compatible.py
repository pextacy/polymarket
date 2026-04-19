from __future__ import annotations

import json
from typing import Optional, Type, TypeVar

from openai import AsyncOpenAI
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleProvider:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        default_model: str,
        default_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers=default_headers,
        )
        self._default_model = default_model

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        response = await self._client.chat.completions.create(
            model=model or self._default_model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        content = response.choices[0].message.content or ""
        return content.strip()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def complete_json(
        self,
        system: str,
        user: str,
        schema: Type[T],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> T:
        schema_json = schema.model_json_schema()
        system_with_schema = (
            f"{system}\n\nRespond ONLY with valid JSON matching this schema:\n"
            f"{json.dumps(schema_json, indent=2)}"
        )

        raw = await self.complete(
            system=system_with_schema,
            user=user,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )

        raw = raw.strip()
        if raw.startswith("```"):
            lines = raw.splitlines()
            raw = "\n".join(
                line for line in lines if not line.strip().startswith("```")
            )

        parsed = json.loads(raw)
        return schema.model_validate(parsed)
