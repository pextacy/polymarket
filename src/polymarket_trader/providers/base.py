from __future__ import annotations

from typing import Optional, Protocol, Type, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(Protocol):
    async def complete(
        self,
        system: str,
        user: str,
        model: Optional[str] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str: ...

    async def complete_json(
        self,
        system: str,
        user: str,
        schema: Type[T],
        model: Optional[str] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> T: ...
