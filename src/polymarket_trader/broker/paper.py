from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime, date
from typing import Optional

from loguru import logger

from ..models.broker import (
    FillRecord,
    OrderRecord,
    OrderStatus,
    PortfolioState,
    PositionState,
)
from ..models.trade import ExecutionPlan, Side
from .base import BaseBroker


class PaperBroker(BaseBroker):
    def __init__(
        self,
        initial_cash: float = 10_000.0,
        fill_slippage_bps: int = 20,
    ) -> None:
        self._cash = initial_cash
        self._slippage = fill_slippage_bps / 10_000
        self._positions: dict[str, PositionState] = {}
        self._orders: list[OrderRecord] = []
        self._fills: list[FillRecord] = []
        self._daily_loss_by_date: dict[date, float] = defaultdict(float)
        self._realized_pnl: float = 0.0

    async def submit(self, plan: ExecutionPlan, run_id: str) -> OrderRecord:
        order_id = str(uuid.uuid4())

        fill_price = plan.estimated_fill_price
        if plan.side == Side.BUY:
            fill_price = min(fill_price * (1 + self._slippage), 0.999)
        else:
            fill_price = max(fill_price * (1 - self._slippage), 0.001)

        cost = plan.size_usdc

        if plan.side == Side.BUY and cost > self._cash:
            logger.warning(
                "Paper: insufficient cash ${:.2f} for order ${:.2f}",
                self._cash,
                cost,
            )
            order = OrderRecord(
                order_id=order_id,
                run_id=run_id,
                condition_id=plan.trade_idea.condition_id,
                token_id=plan.token_id,
                outcome=plan.trade_idea.outcome,
                side=plan.side,
                order_type=plan.order_type,
                size_usdc=plan.size_usdc,
                limit_price=plan.limit_price,
                status=OrderStatus.REJECTED,
            )
            self._orders.append(order)
            return order

        tokens_bought = plan.size_usdc / fill_price if plan.side == Side.BUY else 0.0
        tokens_sold = plan.size_usdc / fill_price if plan.side == Side.SELL else 0.0

        self._apply_fill(
            plan=plan,
            fill_price=fill_price,
            tokens_bought=tokens_bought,
            tokens_sold=tokens_sold,
        )

        fill_id = str(uuid.uuid4())
        fill = FillRecord(
            fill_id=fill_id,
            order_id=order_id,
            run_id=run_id,
            condition_id=plan.trade_idea.condition_id,
            token_id=plan.token_id,
            outcome=plan.trade_idea.outcome,
            side=plan.side,
            filled_size_usdc=plan.size_usdc,
            fill_price=fill_price,
        )
        self._fills.append(fill)

        order = OrderRecord(
            order_id=order_id,
            run_id=run_id,
            condition_id=plan.trade_idea.condition_id,
            token_id=plan.token_id,
            outcome=plan.trade_idea.outcome,
            side=plan.side,
            order_type=plan.order_type,
            size_usdc=plan.size_usdc,
            limit_price=plan.limit_price,
            status=OrderStatus.FILLED,
        )
        self._orders.append(order)

        logger.info(
            "Paper FILL: {} {} ${:.2f} @ {:.4f} (slippage: {:.1f}bps)",
            plan.side.value,
            plan.trade_idea.outcome,
            plan.size_usdc,
            fill_price,
            self._slippage * 10_000,
        )
        return order

    def _apply_fill(
        self,
        plan: ExecutionPlan,
        fill_price: float,
        tokens_bought: float,
        tokens_sold: float,
    ) -> None:
        key = plan.token_id

        if plan.side == Side.BUY:
            self._cash -= plan.size_usdc
            if key not in self._positions:
                self._positions[key] = PositionState(
                    condition_id=plan.trade_idea.condition_id,
                    token_id=plan.token_id,
                    outcome=plan.trade_idea.outcome,
                    category=plan.trade_idea.category,
                )
            pos = self._positions[key]
            total_tokens = pos.size_tokens + tokens_bought
            total_cost = pos.cost_basis_usdc + plan.size_usdc
            pos.avg_entry_price = total_cost / total_tokens if total_tokens > 0 else fill_price
            pos.size_tokens = total_tokens
            pos.cost_basis_usdc = total_cost
            pos.updated_at = datetime.utcnow()

        else:  # SELL
            if key not in self._positions or self._positions[key].size_tokens <= 0:
                logger.warning("Paper: no position to sell for {}", key)
                return
            pos = self._positions[key]
            sell_tokens = min(tokens_sold, pos.size_tokens)
            proceeds = sell_tokens * fill_price
            cost_of_sold = sell_tokens * pos.avg_entry_price
            pnl = proceeds - cost_of_sold

            self._cash += proceeds
            self._realized_pnl += pnl
            pos.realized_pnl += pnl
            pos.size_tokens -= sell_tokens
            pos.cost_basis_usdc -= cost_of_sold
            pos.updated_at = datetime.utcnow()

            today = date.today()
            if pnl < 0:
                self._daily_loss_by_date[today] += abs(pnl)

    async def get_portfolio(self) -> PortfolioState:
        today = date.today()
        return PortfolioState(
            cash_usdc=self._cash,
            positions={k: v for k, v in self._positions.items() if v.size_tokens > 0},
            realized_pnl=self._realized_pnl,
            daily_loss=self._daily_loss_by_date.get(today, 0.0),
        )

    async def open_order_count(self) -> int:
        return sum(
            1
            for o in self._orders
            if o.status == OrderStatus.PENDING
        )

    def get_fills(self) -> list[FillRecord]:
        return list(self._fills)

    def get_orders(self) -> list[OrderRecord]:
        return list(self._orders)
