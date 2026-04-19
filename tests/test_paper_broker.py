from __future__ import annotations

import pytest

from polymarket_trader.broker.paper import PaperBroker
from polymarket_trader.models.broker import OrderStatus
from polymarket_trader.models.trade import ExecutionPlan, OrderType, Side, TradeIdea


def make_plan(
    condition_id: str = "cond1",
    size_usdc: float = 50.0,
    side: Side = Side.BUY,
    limit_price: float = 0.45,
) -> ExecutionPlan:
    idea = TradeIdea(
        condition_id=condition_id,
        question="Will X happen?",
        token_id="tok_yes",
        outcome="Yes",
        side=side,
        fair_probability=0.65,
        market_price=limit_price,
        edge_bps=2000,
        confidence=0.8,
        rationale="Evidence.",
    )
    return ExecutionPlan(
        trade_idea=idea,
        token_id="tok_yes",
        side=side,
        order_type=OrderType.FOK,
        size_usdc=size_usdc,
        limit_price=limit_price,
        estimated_fill_price=limit_price,
        estimated_slippage_bps=20,
        tick_size=0.01,
    )


class TestPaperBroker:
    @pytest.mark.asyncio
    async def test_buy_reduces_cash(self) -> None:
        broker = PaperBroker(initial_cash=1000.0, fill_slippage_bps=0)
        order = await broker.submit(make_plan(size_usdc=100.0, side=Side.BUY), "run1")
        assert order.status == OrderStatus.FILLED
        portfolio = await broker.get_portfolio()
        assert portfolio.cash_usdc == pytest.approx(900.0, abs=1.0)

    @pytest.mark.asyncio
    async def test_buy_creates_position(self) -> None:
        broker = PaperBroker(initial_cash=1000.0, fill_slippage_bps=0)
        await broker.submit(make_plan(size_usdc=50.0, side=Side.BUY, limit_price=0.50), "run1")
        portfolio = await broker.get_portfolio()
        assert "tok_yes" in portfolio.positions
        pos = portfolio.positions["tok_yes"]
        assert pos.size_tokens == pytest.approx(100.0, rel=0.05)

    @pytest.mark.asyncio
    async def test_insufficient_cash_rejects(self) -> None:
        broker = PaperBroker(initial_cash=10.0, fill_slippage_bps=0)
        order = await broker.submit(make_plan(size_usdc=100.0, side=Side.BUY), "run1")
        assert order.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_buy_then_sell_pnl(self) -> None:
        broker = PaperBroker(initial_cash=1000.0, fill_slippage_bps=0)
        await broker.submit(
            make_plan(size_usdc=100.0, side=Side.BUY, limit_price=0.50), "r1"
        )

        sell_plan = make_plan(size_usdc=100.0, side=Side.SELL, limit_price=0.70)
        sell_plan.trade_idea.side = Side.SELL
        sell_plan.side = Side.SELL
        await broker.submit(sell_plan, "r1")

        portfolio = await broker.get_portfolio()
        assert portfolio.realized_pnl > 0

    @pytest.mark.asyncio
    async def test_fill_recorded(self) -> None:
        broker = PaperBroker(initial_cash=1000.0, fill_slippage_bps=0)
        await broker.submit(make_plan(size_usdc=50.0, side=Side.BUY), "run1")
        fills = broker.get_fills()
        assert len(fills) == 1
        assert fills[0].filled_size_usdc == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_open_order_count_is_zero_after_fill(self) -> None:
        broker = PaperBroker(initial_cash=1000.0, fill_slippage_bps=0)
        await broker.submit(make_plan(size_usdc=50.0, side=Side.BUY), "run1")
        count = await broker.open_order_count()
        assert count == 0

    @pytest.mark.asyncio
    async def test_multiple_buys_same_market_average_price(self) -> None:
        broker = PaperBroker(initial_cash=10_000.0, fill_slippage_bps=0)
        await broker.submit(
            make_plan(size_usdc=100.0, side=Side.BUY, limit_price=0.40), "r1"
        )
        await broker.submit(
            make_plan(size_usdc=100.0, side=Side.BUY, limit_price=0.60), "r1"
        )
        portfolio = await broker.get_portfolio()
        pos = portfolio.positions["tok_yes"]
        assert pos.avg_entry_price == pytest.approx(0.50, rel=0.05)
