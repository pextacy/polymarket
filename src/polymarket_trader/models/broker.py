from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .trade import Side, OrderType


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    EXPIRED = "expired"


class OrderRecord(BaseModel):
    order_id: str
    run_id: str
    condition_id: str
    token_id: str
    outcome: str
    side: Side
    order_type: OrderType
    size_usdc: float
    limit_price: float
    status: OrderStatus = OrderStatus.PENDING
    exchange_order_id: Optional[str] = None
    submitted_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    raw_response: Optional[dict] = None


class FillRecord(BaseModel):
    fill_id: str
    order_id: str
    run_id: str
    condition_id: str
    token_id: str
    outcome: str
    side: Side
    filled_size_usdc: float
    fill_price: float
    fee_usdc: float = 0.0
    filled_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def net_cost_usdc(self) -> float:
        if self.side == Side.BUY:
            return self.filled_size_usdc + self.fee_usdc
        return -(self.filled_size_usdc - self.fee_usdc)


class PositionState(BaseModel):
    condition_id: str
    token_id: str
    outcome: str
    category: str = "general"
    size_tokens: float = 0.0
    avg_entry_price: float = 0.0
    realized_pnl: float = 0.0
    cost_basis_usdc: float = 0.0
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def unrealized_pnl(self, current_price: float) -> float:
        return self.size_tokens * (current_price - self.avg_entry_price)

    def market_value(self, current_price: float) -> float:
        return self.size_tokens * current_price


class PortfolioState(BaseModel):
    cash_usdc: float
    positions: dict[str, PositionState] = Field(default_factory=dict)
    realized_pnl: float = 0.0
    daily_loss: float = 0.0
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def total_exposure(self, prices: dict[str, float]) -> float:
        return sum(
            pos.market_value(prices.get(pos.token_id, pos.avg_entry_price))
            for pos in self.positions.values()
        )

    def unrealized_pnl(self, prices: dict[str, float]) -> float:
        return sum(
            pos.unrealized_pnl(prices.get(pos.token_id, pos.avg_entry_price))
            for pos in self.positions.values()
        )

    def open_position_count(self) -> int:
        return sum(1 for pos in self.positions.values() if pos.size_tokens > 0)

    def category_exposure(self, category: str, prices: dict[str, float]) -> float:
        return sum(
            pos.market_value(prices.get(pos.token_id, pos.avg_entry_price))
            for pos in self.positions.values()
            if pos.category == category and pos.size_tokens > 0
        )
