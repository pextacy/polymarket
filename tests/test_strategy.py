from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from polymarket_trader.config import Settings
from polymarket_trader.models.forecast import Forecast, OpportunityScore, OutcomeProbability
from polymarket_trader.models.market import MarketSnapshot, TokenInfo
from polymarket_trader.models.trade import Side
from polymarket_trader.strategy.planner import ExecutionPlanner
from polymarket_trader.strategy.scorer import OpportunityScorer


def make_settings(**overrides) -> Settings:
    base = {
        "openrouter_api_key": "test-key",
        "risk_max_notional_per_market": 100.0,
        "paper_initial_cash": 10_000.0,
        "paper_fill_slippage_bps": 20,
        "scan_min_edge_bps": 200,
    }
    base.update(overrides)
    return Settings(**base)


def make_market(
    best_bid: float = 0.40,
    best_ask: float = 0.50,
    tick_size: float = 0.01,
    min_order_size: float = 1.0,
    hours_to_expiry: float = 72.0,
    liquidity: float = 5000.0,
) -> MarketSnapshot:
    return MarketSnapshot(
        condition_id="cond1",
        question_id="q1",
        question="Will X?",
        tokens=[
            TokenInfo(token_id="tok_yes", outcome="Yes", price=best_bid),
            TokenInfo(token_id="tok_no", outcome="No", price=1 - best_ask),
        ],
        best_bid=best_bid,
        best_ask=best_ask,
        tick_size=tick_size,
        min_order_size=min_order_size,
        volume_24h=10_000.0,
        liquidity=liquidity,
        end_date=datetime.utcnow() + timedelta(hours=hours_to_expiry),
    )


def make_forecast(yes_fair: float = 0.65, market_price: float = 0.45) -> Forecast:
    return Forecast(
        condition_id="cond1",
        confidence=0.8,
        rationale="Supporting evidence found.",
        outcomes=[
            OutcomeProbability(
                outcome="Yes",
                token_id="tok_yes",
                fair_probability=yes_fair,
                market_price=market_price,
            ),
            OutcomeProbability(
                outcome="No",
                token_id="tok_no",
                fair_probability=round(1 - yes_fair, 4),
                market_price=round(1 - market_price, 4),
            ),
        ],
        model_used="openai/gpt-4o",
    )


class TestOpportunityScorer:
    def test_returns_score_when_edge_sufficient(self) -> None:
        scorer = OpportunityScorer()
        market = make_market()
        forecast = make_forecast(yes_fair=0.70, market_price=0.45)
        score = scorer.score(market, forecast, min_edge_bps=200)
        assert score is not None
        assert score.edge_bps > 200

    def test_returns_none_when_edge_insufficient(self) -> None:
        scorer = OpportunityScorer()
        market = make_market()
        forecast = make_forecast(yes_fair=0.46, market_price=0.45)
        score = scorer.score(market, forecast, min_edge_bps=200)
        assert score is None

    def test_score_is_positive(self) -> None:
        scorer = OpportunityScorer()
        market = make_market(liquidity=10_000.0)
        forecast = make_forecast(yes_fair=0.75)
        score = scorer.score(market, forecast, min_edge_bps=200)
        assert score is not None
        assert score.final_score > 0


class TestExecutionPlanner:
    def test_buy_plan_for_positive_edge(self) -> None:
        planner = ExecutionPlanner(make_settings())
        market = make_market()
        forecast = make_forecast(yes_fair=0.70, market_price=0.45)
        scorer = OpportunityScorer()
        score = scorer.score(market, forecast, min_edge_bps=200)
        assert score is not None

        plan = planner.plan(score, market, portfolio_cash=10_000.0)
        assert plan is not None
        assert plan.side == Side.BUY
        assert plan.size_usdc > 0
        assert plan.size_usdc <= 100.0

    def test_plan_respects_tick_size(self) -> None:
        planner = ExecutionPlanner(make_settings())
        market = make_market(tick_size=0.01, best_ask=0.453)
        forecast = make_forecast(yes_fair=0.70, market_price=0.45)
        scorer = OpportunityScorer()
        score = scorer.score(market, forecast, min_edge_bps=200)
        assert score is not None

        plan = planner.plan(score, market, portfolio_cash=10_000.0)
        assert plan is not None
        remainder = round(plan.limit_price % 0.01, 8)
        assert remainder < 1e-7 or abs(remainder - 0.01) < 1e-7

    def test_no_plan_when_size_below_minimum(self) -> None:
        planner = ExecutionPlanner(
            make_settings(risk_max_notional_per_market=100.0, paper_initial_cash=1.0)
        )
        market = make_market(min_order_size=10.0)
        forecast = make_forecast(yes_fair=0.70, market_price=0.45)
        scorer = OpportunityScorer()
        score = scorer.score(market, forecast)
        assert score is not None

        plan = planner.plan(score, market, portfolio_cash=1.0)
        assert plan is None
