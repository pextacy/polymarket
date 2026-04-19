from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from polymarket_trader.models.market import MarketSnapshot, TokenInfo
from polymarket_trader.models.forecast import Forecast, OutcomeProbability, OpportunityScore
from polymarket_trader.models.trade import ExecutionPlan, TradeIdea, Side, OrderType
from polymarket_trader.models.broker import PortfolioState, PositionState
from polymarket_trader.models.run import RunRecord, RunStatus


def make_market(
    condition_id: str = "abc123",
    best_bid: float = 0.42,
    best_ask: float = 0.48,
    hours_to_expiry: float = 72.0,
    liquidity: float = 5000.0,
) -> MarketSnapshot:
    end_date = datetime.utcnow() + timedelta(hours=hours_to_expiry)
    return MarketSnapshot(
        condition_id=condition_id,
        question_id="q1",
        question="Will X happen by Y?",
        tokens=[
            TokenInfo(token_id="tok_yes", outcome="Yes", price=best_bid),
            TokenInfo(token_id="tok_no", outcome="No", price=1 - best_ask),
        ],
        best_bid=best_bid,
        best_ask=best_ask,
        spread=round(best_ask - best_bid, 4),
        tick_size=0.01,
        min_order_size=1.0,
        volume_24h=10_000.0,
        liquidity=liquidity,
        end_date=end_date,
    )


def make_forecast(condition_id: str = "abc123", yes_prob: float = 0.65) -> Forecast:
    return Forecast(
        condition_id=condition_id,
        confidence=0.8,
        rationale="Strong evidence supports yes outcome.",
        sources_used=["https://example.com/news"],
        outcomes=[
            OutcomeProbability(
                outcome="Yes",
                token_id="tok_yes",
                fair_probability=yes_prob,
                market_price=0.45,
            ),
            OutcomeProbability(
                outcome="No",
                token_id="tok_no",
                fair_probability=round(1 - yes_prob, 4),
                market_price=0.55,
            ),
        ],
        model_used="openai/gpt-4o",
    )


class TestMarketSnapshot:
    def test_yes_token_identified(self) -> None:
        m = make_market()
        assert m.yes_token is not None
        assert m.yes_token.outcome == "Yes"

    def test_mid_price(self) -> None:
        m = make_market(best_bid=0.40, best_ask=0.50)
        assert m.mid_price == pytest.approx(0.45)

    def test_hours_to_expiry(self) -> None:
        m = make_market(hours_to_expiry=24.0)
        assert m.hours_to_expiry is not None
        assert 23.5 < m.hours_to_expiry < 24.5

    def test_no_expiry(self) -> None:
        m = MarketSnapshot(
            condition_id="x",
            question_id="q",
            question="Q?",
            tokens=[],
        )
        assert m.hours_to_expiry is None


class TestForecast:
    def test_best_outcome_is_highest_edge(self) -> None:
        f = make_forecast(yes_prob=0.70)
        best = f.best_outcome()
        assert best is not None
        assert best.outcome == "Yes"
        assert best.edge_bps == pytest.approx((0.70 - 0.45) * 10_000)

    def test_outcome_probabilities_accessible(self) -> None:
        f = make_forecast(yes_prob=0.60)
        assert len(f.outcomes) == 2
        yes_outcomes = [o for o in f.outcomes if o.outcome == "Yes"]
        assert yes_outcomes[0].fair_probability == pytest.approx(0.60)


class TestOpportunityScore:
    def test_compute_score_positive(self) -> None:
        m = make_market(hours_to_expiry=48.0, liquidity=5000.0)
        f = make_forecast(yes_prob=0.70)
        score = OpportunityScore(
            condition_id="abc",
            question="Q?",
            category="politics",
            edge_bps=2500.0,
            confidence=0.8,
            liquidity=5000.0,
            volume_24h=10000.0,
            hours_to_expiry=48.0,
            forecast=f,
        )
        result = score.compute_score()
        assert result > 0

    def test_score_zero_near_expiry(self) -> None:
        f = make_forecast()
        score = OpportunityScore(
            condition_id="abc",
            question="Q?",
            category="politics",
            edge_bps=3000.0,
            confidence=0.9,
            liquidity=5000.0,
            volume_24h=10000.0,
            hours_to_expiry=1.0,
            forecast=f,
        )
        result = score.compute_score()
        assert result == pytest.approx(0.0)


class TestPortfolioState:
    def test_open_position_count(self) -> None:
        portfolio = PortfolioState(
            cash_usdc=1000.0,
            positions={
                "tok1": PositionState(
                    condition_id="c1",
                    token_id="tok1",
                    outcome="Yes",
                    size_tokens=10.0,
                    avg_entry_price=0.5,
                ),
                "tok2": PositionState(
                    condition_id="c2",
                    token_id="tok2",
                    outcome="No",
                    size_tokens=0.0,
                    avg_entry_price=0.3,
                ),
            },
        )
        assert portfolio.open_position_count() == 1

    def test_unrealized_pnl(self) -> None:
        portfolio = PortfolioState(
            cash_usdc=1000.0,
            positions={
                "tok1": PositionState(
                    condition_id="c1",
                    token_id="tok1",
                    outcome="Yes",
                    size_tokens=10.0,
                    avg_entry_price=0.40,
                ),
            },
        )
        pnl = portfolio.unrealized_pnl({"tok1": 0.60})
        assert pnl == pytest.approx(2.0)
