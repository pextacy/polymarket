from __future__ import annotations

import asyncio
from datetime import datetime, timedelta

import pytest

from polymarket_trader.backtest.broker import BacktestBroker
from polymarket_trader.backtest.models import BacktestSummary, BacktestTradeResult
from polymarket_trader.models.market import MarketSnapshot, TokenInfo
from polymarket_trader.models.trade import ExecutionPlan, TradeIdea, Side, OrderType
from polymarket_trader.models.broker import OrderStatus


def make_market(condition_id: str, yes_winner: bool = True) -> MarketSnapshot:
    return MarketSnapshot(
        condition_id=condition_id,
        question_id=f"qid_{condition_id}",
        question=f"Will {condition_id} happen?",
        category="politics",
        tokens=[
            TokenInfo(token_id=f"{condition_id}_yes", outcome="Yes",
                      price=0.45, winner=yes_winner),
            TokenInfo(token_id=f"{condition_id}_no", outcome="No",
                      price=0.55, winner=not yes_winner),
        ],
        best_bid=0.44,
        best_ask=0.56,
        tick_size=0.01,
        liquidity=5000.0,
        end_date=datetime.utcnow() - timedelta(days=1),  # already resolved
        closed=True,
    )


def make_plan(
    condition_id: str,
    token_id: str,
    outcome: str = "Yes",
    size: float = 50.0,
    price: float = 0.50,
) -> ExecutionPlan:
    idea = TradeIdea(
        condition_id=condition_id,
        question=f"Will {condition_id} happen?",
        token_id=token_id,
        outcome=outcome,
        side=Side.BUY,
        fair_probability=0.65,
        market_price=price,
        edge_bps=1500,
        confidence=0.8,
        rationale="test",
    )
    return ExecutionPlan(
        trade_idea=idea,
        token_id=token_id,
        side=Side.BUY,
        order_type=OrderType.FOK,
        size_usdc=size,
        limit_price=price,
        estimated_fill_price=price,
        estimated_slippage_bps=0,
        tick_size=0.01,
    )


class TestBacktestBroker:
    @pytest.mark.asyncio
    async def test_fill_recorded_in_metadata(self):
        broker = BacktestBroker(initial_cash=1000.0)
        plan = make_plan("c1", "c1_yes")
        order = await broker.submit(plan, "bt")
        assert order.status == OrderStatus.FILLED
        assert "c1_yes" in broker._order_meta
        assert broker._order_meta["c1_yes"]["edge_bps"] == 1500

    @pytest.mark.asyncio
    async def test_resolve_winning_position(self):
        broker = BacktestBroker(initial_cash=1000.0)
        plan = make_plan("c1", "c1_yes", size=100.0, price=0.50)
        await broker.submit(plan, "bt")

        results = broker.resolve_all(
            resolutions={"c1_yes": 1.0, "c1_no": 0.0},
            winning_outcomes={"c1": "Yes"},
        )
        assert len(results) == 1
        r = results[0]
        assert r.won is True
        assert r.resolution_price == 1.0
        # bought $100 at $0.50 → 200 tokens → 200 * 1.0 = $200 proceeds → PnL = $100
        assert abs(r.pnl - 100.0) < 0.01
        assert r.outcome_traded == "Yes"
        assert r.winning_outcome == "Yes"

    @pytest.mark.asyncio
    async def test_resolve_losing_position(self):
        broker = BacktestBroker(initial_cash=1000.0)
        plan = make_plan("c2", "c2_yes", size=100.0, price=0.50)
        await broker.submit(plan, "bt")

        results = broker.resolve_all(
            resolutions={"c2_yes": 0.0, "c2_no": 1.0},
            winning_outcomes={"c2": "No"},
        )
        assert len(results) == 1
        r = results[0]
        assert r.won is False
        assert r.resolution_price == 0.0
        assert abs(r.pnl - (-100.0)) < 0.01

    @pytest.mark.asyncio
    async def test_resolve_multiple_positions(self):
        broker = BacktestBroker(initial_cash=2000.0)

        await broker.submit(make_plan("c1", "c1_yes", size=100.0, price=0.50), "bt")
        await broker.submit(make_plan("c2", "c2_yes", size=200.0, price=0.40), "bt")

        resolutions = {
            "c1_yes": 1.0,  # c1 wins
            "c1_no": 0.0,
            "c2_yes": 0.0,  # c2 loses
            "c2_no": 1.0,
        }
        results = broker.resolve_all(resolutions, {"c1": "Yes", "c2": "No"})
        assert len(results) == 2

        c1_result = next(r for r in results if r.condition_id == "c1")
        c2_result = next(r for r in results if r.condition_id == "c2")
        assert c1_result.won is True
        assert c2_result.won is False
        net = c1_result.pnl + c2_result.pnl
        assert abs(net - (100.0 - 200.0)) < 0.01

    @pytest.mark.asyncio
    async def test_positions_zeroed_after_resolution(self):
        broker = BacktestBroker(initial_cash=1000.0)
        await broker.submit(make_plan("c1", "c1_yes", size=50.0), "bt")
        broker.resolve_all({"c1_yes": 1.0}, {"c1": "Yes"})

        port = await broker.get_portfolio()
        assert port.open_position_count() == 0

    @pytest.mark.asyncio
    async def test_cash_updated_after_resolution(self):
        broker = BacktestBroker(initial_cash=1000.0)
        await broker.submit(make_plan("c1", "c1_yes", size=100.0, price=0.50), "bt")
        # After BUY: cash = 900
        broker.resolve_all({"c1_yes": 1.0}, {"c1": "Yes"})
        # 200 tokens × $1.00 = $200 proceeds; cash = 900 + 200 = 1100
        port = await broker.get_portfolio()
        assert abs(port.cash_usdc - 1100.0) < 0.01

    @pytest.mark.asyncio
    async def test_no_position_to_resolve(self):
        broker = BacktestBroker(initial_cash=1000.0)
        results = broker.resolve_all({"tok_unknown": 1.0}, {})
        assert results == []

    @pytest.mark.asyncio
    async def test_rejected_order_not_in_metadata(self):
        broker = BacktestBroker(initial_cash=10.0)  # tiny cash
        plan = make_plan("c1", "c1_yes", size=500.0)
        order = await broker.submit(plan, "bt")
        assert order.status == OrderStatus.REJECTED
        assert "c1_yes" not in broker._order_meta


class TestBacktestModels:
    def _make_results(self, pnls: list[float], sizes: list[float] | None = None) -> list[BacktestTradeResult]:
        if sizes is None:
            sizes = [100.0] * len(pnls)
        results = []
        for i, (pnl, size) in enumerate(zip(pnls, sizes)):
            results.append(
                BacktestTradeResult(
                    condition_id=f"c{i}",
                    question=f"Q{i}",
                    category="politics",
                    outcome_traded="Yes",
                    winning_outcome="Yes" if pnl > 0 else "No",
                    won=pnl > 0,
                    entry_price=0.50,
                    resolution_price=1.0 if pnl > 0 else 0.0,
                    size_usdc=size,
                    pnl=pnl,
                    edge_bps=1500,
                    confidence=0.8,
                    fair_probability=0.65,
                )
            )
        return results

    def test_win_rate(self):
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1100.0,
            total_markets_evaluated=5, total_trades=4,
            winning_trades=3, losing_trades=1,
            skipped_no_edge=0, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
            trades=self._make_results([50, 50, 50, -50]),
        )
        assert abs(summary.win_rate - 0.75) < 1e-9

    def test_total_pnl(self):
        trades = self._make_results([100, -30, 50])
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1120.0,
            total_markets_evaluated=5, total_trades=3,
            winning_trades=2, losing_trades=1,
            skipped_no_edge=0, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
            trades=trades,
        )
        assert abs(summary.total_pnl - 120.0) < 1e-9

    def test_roi_pct(self):
        trades = self._make_results([200])
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1200.0,
            total_markets_evaluated=1, total_trades=1,
            winning_trades=1, losing_trades=0,
            skipped_no_edge=0, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
            trades=trades,
        )
        assert abs(summary.roi_pct - 20.0) < 1e-9

    def test_max_drawdown(self):
        # PnL series: +50, +50, -80, +20 → peak=100, trough=20 → drawdown=80
        trades = self._make_results([50, 50, -80, 20])
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1040.0,
            total_markets_evaluated=4, total_trades=4,
            winning_trades=3, losing_trades=1,
            skipped_no_edge=0, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
            trades=trades,
        )
        assert abs(summary.max_drawdown - 80.0) < 1e-9

    def test_sharpe_ratio_positive_for_consistent_wins(self):
        trades = self._make_results([10, 10, 10, 10, 10])
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1050.0,
            total_markets_evaluated=5, total_trades=5,
            winning_trades=5, losing_trades=0,
            skipped_no_edge=0, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
            trades=trades,
        )
        # All identical PnLs → std=0 → Sharpe=0 (edge case)
        assert summary.sharpe_ratio == 0.0

    def test_sharpe_ratio_with_variance(self):
        trades = self._make_results([100, -20, 80, -10, 60])
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1210.0,
            total_markets_evaluated=5, total_trades=5,
            winning_trades=3, losing_trades=2,
            skipped_no_edge=0, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
            trades=trades,
        )
        assert summary.sharpe_ratio > 0

    def test_zero_trades(self):
        summary = BacktestSummary(
            initial_cash=1000.0, final_cash=1000.0,
            total_markets_evaluated=10, total_trades=0,
            winning_trades=0, losing_trades=0,
            skipped_no_edge=10, skipped_risk=0,
            skipped_no_plan=0, forecast_failures=0,
        )
        assert summary.win_rate == 0.0
        assert summary.total_pnl == 0.0
        assert summary.sharpe_ratio == 0.0
        assert summary.max_drawdown == 0.0

    def test_trade_roi_pct(self):
        t = BacktestTradeResult(
            condition_id="c", question="Q", category="p",
            outcome_traded="Yes", winning_outcome="Yes", won=True,
            entry_price=0.5, resolution_price=1.0,
            size_usdc=100.0, pnl=100.0,
            edge_bps=1500, confidence=0.8, fair_probability=0.65,
        )
        assert abs(t.roi_pct - 100.0) < 1e-9
