from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    FOK = "FOK"
    FAK = "FAK"
    GTC = "GTC"


class TradeIdea(BaseModel):
    condition_id: str
    question: str
    category: str = "general"
    token_id: str
    outcome: str
    side: Side
    fair_probability: float
    market_price: float
    edge_bps: float
    confidence: float
    rationale: str
    source_urls: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ExecutionPlan(BaseModel):
    trade_idea: TradeIdea
    token_id: str
    side: Side
    order_type: OrderType
    size_usdc: float
    limit_price: float
    estimated_fill_price: float
    estimated_slippage_bps: float
    tick_size: float
    planned_at: datetime = Field(default_factory=datetime.utcnow)

    def validate_tick_size(self) -> bool:
        remainder = round(self.limit_price % self.tick_size, 8)
        return remainder < 1e-8 or abs(remainder - self.tick_size) < 1e-8

    def snap_to_tick(self, price: float) -> float:
        ticks = round(price / self.tick_size)
        return round(ticks * self.tick_size, 8)
