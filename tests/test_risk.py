from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from polymarket_trader.config import Settings
from polymarket_trader.models.broker import PortfolioState
from polymarket_trader.models.market import MarketSnapshot, TokenInfo
from polymarket_trader.models.risk import RiskVerdictType
from polymarket_trader.models.trade import ExecutionPlan, OrderType, Side, TradeIdea
from polymarket_trader.risk.engine import RiskEngine


def make_settings(**overrides) -> Settings:
    base = {
        "openrouter_api_key": "test-key",
        "risk_max_notional_per_market": 50.0,
        "risk_max_portfolio_exposure": 500.0,
        "risk_max_category_exposure": 150.0,
        "risk_max_daily_loss": 100.0,
        "risk_max_open_positions": 5,
        "risk_max_open_orders": 10,
        "risk_signal_staleness_seconds": 3600,
        "risk_expiry_no_trade_hours": 2,
        "risk_cooldown_after_losses": 3,
        "risk_cooldown_duration_seconds": 60,
    }
    base.update(overrides)
    return Settings(**base)


def make_plan(size_usdc: float = 30.0, age_seconds: float = 0) -> ExecutionPlan:
    planned_at = datetime.utcnow() - timedelta(seconds=age_seconds)
    idea = TradeIdea(
        condition_id="cond1",
        question="Will it rain?",
        token_id="tok_yes",
        outcome="Yes",
        side=Side.BUY,
        fair_probability=0.70,
        market_price=0.45,
        edge_bps=2500,
        confidence=0.8,
        rationale="Evidence supports yes.",
    )
    return ExecutionPlan(
        trade_idea=idea,
        token_id="tok_yes",
        side=Side.BUY,
        order_type=OrderType.FOK,
        size_usdc=size_usdc,
        limit_price=0.46,
        estimated_fill_price=0.461,
        estimated_slippage_bps=20,
        tick_size=0.01,
        planned_at=planned_at,
    )


def make_market(hours_to_expiry: float = 48.0) -> MarketSnapshot:
    end_date = datetime.utcnow() + timedelta(hours=hours_to_expiry)
    return MarketSnapshot(
        condition_id="cond1",
        question_id="q1",
        question="Will it rain?",
        tokens=[TokenInfo(token_id="tok_yes", outcome="Yes", price=0.45)],
        end_date=end_date,
    )


def empty_portfolio() -> PortfolioState:
    return PortfolioState(cash_usdc=10_000.0)


class TestRiskEngine:
    def test_approves_valid_trade(self) -> None:
        engine = RiskEngine(make_settings())
        decision = engine.evaluate(make_plan(), make_market(), empty_portfolio(), 0)
        assert decision.approved

    def test_rejects_stale_signal(self) -> None:
        engine = RiskEngine(make_settings(risk_signal_staleness_seconds=60))
        plan = make_plan(age_seconds=120)
        decision = engine.evaluate(plan, make_market(), empty_portfolio(), 0)
        assert not decision.approved
        assert any("stale" in r for r in decision.reasons)

    def test_rejects_near_expiry(self) -> None:
        engine = RiskEngine(make_settings(risk_expiry_no_trade_hours=4))
        decision = engine.evaluate(
            make_plan(), make_market(hours_to_expiry=1.0), empty_portfolio(), 0
        )
        assert not decision.approved
        assert any("expires" in r for r in decision.reasons)

    def test_rejects_oversized_notional(self) -> None:
        engine = RiskEngine(make_settings(risk_max_notional_per_market=20.0))
        decision = engine.evaluate(make_plan(size_usdc=30.0), make_market(), empty_portfolio(), 0)
        assert not decision.approved
        assert any("notional" in r for r in decision.reasons)

    def test_rejects_too_many_open_orders(self) -> None:
        engine = RiskEngine(make_settings(risk_max_open_orders=5))
        decision = engine.evaluate(make_plan(), make_market(), empty_portfolio(), 6)
        assert not decision.approved
        assert any("orders" in r for r in decision.reasons)

    def test_cooldown_after_consecutive_losses(self) -> None:
        settings = make_settings(
            risk_cooldown_after_losses=2, risk_cooldown_duration_seconds=60
        )
        engine = RiskEngine(settings)
        engine.record_loss("cond1")
        engine.record_loss("cond1")

        decision = engine.evaluate(make_plan(), make_market(), empty_portfolio(), 0)
        assert not decision.approved
        assert any("cooldown" in r for r in decision.reasons)

    def test_win_resets_loss_streak(self) -> None:
        settings = make_settings(
            risk_cooldown_after_losses=3, risk_cooldown_duration_seconds=60
        )
        engine = RiskEngine(settings)
        engine.record_loss("cond1")
        engine.record_loss("cond1")
        engine.record_win("cond1")
        engine.record_loss("cond1")

        decision = engine.evaluate(make_plan(), make_market(), empty_portfolio(), 0)
        assert decision.approved

    def test_rejects_daily_loss_exceeded(self) -> None:
        engine = RiskEngine(make_settings(risk_max_daily_loss=50.0))
        portfolio = PortfolioState(cash_usdc=10_000.0, daily_loss=60.0)
        decision = engine.evaluate(make_plan(), make_market(), portfolio, 0)
        assert not decision.approved
        assert any("daily loss" in r for r in decision.reasons)

    def test_rejects_category_exposure_exceeded(self) -> None:
        from polymarket_trader.models.broker import PositionState
        engine = RiskEngine(make_settings(risk_max_category_exposure=40.0))
        portfolio = PortfolioState(
            cash_usdc=10_000.0,
            positions={
                "existing_tok": PositionState(
                    condition_id="existing",
                    token_id="existing_tok",
                    outcome="Yes",
                    category="general",
                    size_tokens=100.0,
                    avg_entry_price=0.30,
                    cost_basis_usdc=30.0,
                )
            },
        )
        # existing category exposure = 100 * 0.30 = $30, new plan = $30 → total $60 > $40
        decision = engine.evaluate(make_plan(size_usdc=30.0), make_market(), portfolio, 0)
        assert not decision.approved
        assert any("category" in r for r in decision.reasons)
