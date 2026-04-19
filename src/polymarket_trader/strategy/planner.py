from __future__ import annotations

from typing import Optional

from loguru import logger

from ..config import Settings
from ..models.forecast import OpportunityScore
from ..models.market import MarketSnapshot
from ..models.trade import ExecutionPlan, OrderType, Side, TradeIdea


class ExecutionPlanner:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def plan(
        self,
        score: OpportunityScore,
        market: MarketSnapshot,
        portfolio_cash: float,
    ) -> Optional[ExecutionPlan]:
        forecast = score.forecast
        best = forecast.best_outcome()
        if best is None:
            return None

        side = Side.BUY if best.edge_bps > 0 else Side.SELL

        token = None
        for t in market.tokens:
            if t.token_id == best.token_id:
                token = t
                break
        if token is None:
            logger.warning("Token not found for outcome {}", best.outcome)
            return None

        # For BUY use best_ask if we have book data; otherwise use token price
        # For SELL use best_bid if we have book data; otherwise use token price
        if side == Side.BUY:
            limit_price = (
                market.best_ask
                if market.best_ask > 0 and market.best_ask < 1
                else best.market_price
            )
        else:
            limit_price = (
                market.best_bid
                if market.best_bid > 0 and market.best_bid < 1
                else best.market_price
            )

        if limit_price <= 0 or limit_price >= 1:
            logger.warning("Invalid limit price {:.4f} for {}", limit_price, market.condition_id)
            return None

        from ..config import TradingMode
        slippage_bps = (
            self._settings.live_fill_slippage_bps
            if self._settings.trading_mode == TradingMode.LIVE
            else self._settings.paper_fill_slippage_bps
        )
        slippage = slippage_bps / 10_000
        if side == Side.BUY:
            estimated_fill = min(limit_price * (1 + slippage), 0.99)
        else:
            estimated_fill = max(limit_price * (1 - slippage), 0.01)

        kelly_fraction = self._kelly_size(
            fair_prob=best.fair_probability,
            market_price=limit_price,
            confidence=forecast.confidence,
        )
        size_usdc = min(
            kelly_fraction * portfolio_cash,
            self._settings.risk_max_notional_per_market,
        )

        if size_usdc < market.min_order_size:
            logger.debug(
                "Size ${:.2f} below min order size for {}",
                size_usdc,
                market.condition_id,
            )
            return None

        limit_price = self._snap_to_tick(limit_price, market.tick_size)

        trade_idea = TradeIdea(
            condition_id=market.condition_id,
            question=market.question,
            category=market.category,
            token_id=best.token_id,
            outcome=best.outcome,
            side=side,
            fair_probability=best.fair_probability,
            market_price=best.market_price,
            edge_bps=best.edge_bps,
            confidence=forecast.confidence,
            rationale=forecast.rationale,
            source_urls=forecast.sources_used,
        )

        return ExecutionPlan(
            trade_idea=trade_idea,
            token_id=best.token_id,
            side=side,
            order_type=OrderType.FOK,
            size_usdc=round(size_usdc, 2),
            limit_price=limit_price,
            estimated_fill_price=estimated_fill,
            estimated_slippage_bps=slippage * 10_000,
            tick_size=market.tick_size,
        )

    def _kelly_size(
        self,
        fair_prob: float,
        market_price: float,
        confidence: float,
        max_fraction: float = 0.05,
    ) -> float:
        if market_price <= 0 or market_price >= 1:
            return 0.0
        if fair_prob <= 0 or fair_prob >= 1:
            return 0.0
        b = (1 - market_price) / market_price
        q = 1 - fair_prob
        kelly = (fair_prob * b - q) / b
        kelly = max(0.0, kelly)
        scaled = kelly * confidence * 0.25
        return min(scaled, max_fraction)

    def _snap_to_tick(self, price: float, tick_size: float) -> float:
        if tick_size <= 0:
            return round(price, 4)
        ticks = round(price / tick_size)
        return round(ticks * tick_size, 8)
