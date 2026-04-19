from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class TokenInfo(BaseModel):
    token_id: str
    outcome: str
    price: float = 0.0
    winner: bool = False


class MarketSnapshot(BaseModel):
    condition_id: str
    question_id: str
    question: str
    description: str = ""
    category: str = "general"
    slug: str = ""
    resolution_source: str = ""
    end_date: Optional[datetime] = None
    game_start_time: Optional[datetime] = None
    active: bool = True
    closed: bool = False
    archived: bool = False
    tokens: list[TokenInfo] = Field(default_factory=list)
    # CLOB enriched fields
    best_bid: float = 0.0
    best_ask: float = 1.0
    spread: float = 1.0
    tick_size: float = 0.01
    min_order_size: float = 1.0
    volume_24h: float = 0.0
    liquidity: float = 0.0
    # Snapshot metadata
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def yes_token(self) -> Optional[TokenInfo]:
        for t in self.tokens:
            if t.outcome.lower() in ("yes", "true", "1"):
                return t
        return self.tokens[0] if self.tokens else None

    @property
    def no_token(self) -> Optional[TokenInfo]:
        for t in self.tokens:
            if t.outcome.lower() in ("no", "false", "0"):
                return t
        return self.tokens[1] if len(self.tokens) > 1 else None

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2
        yes = self.yes_token
        return yes.price if yes else 0.5

    @property
    def hours_to_expiry(self) -> Optional[float]:
        if self.end_date is None:
            return None
        delta = self.end_date - datetime.utcnow()
        return delta.total_seconds() / 3600
