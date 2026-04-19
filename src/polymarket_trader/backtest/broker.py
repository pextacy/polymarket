from __future__ import annotations

from ..broker.paper import PaperBroker
from ..models.broker import OrderRecord, OrderStatus
from ..models.trade import ExecutionPlan
from .models import BacktestTradeResult


class BacktestBroker(PaperBroker):
    """
    PaperBroker extended with market-resolution support.

    After submitting orders, call resolve_all() with a map of
    token_id → payout (1.0 for the winning token, 0.0 for losers).
    All open positions are closed at those prices and trade results returned.
    """

    def __init__(self, initial_cash: float = 10_000.0) -> None:
        super().__init__(initial_cash=initial_cash, fill_slippage_bps=0)
        # Metadata attached to each filled order for result reporting
        self._order_meta: dict[str, dict] = {}  # token_id → plan metadata

    async def submit(self, plan: ExecutionPlan, run_id: str) -> OrderRecord:
        order = await super().submit(plan, run_id)
        if order.status == OrderStatus.FILLED:
            self._order_meta[plan.token_id] = {
                "question": plan.trade_idea.question,
                "category": plan.trade_idea.category,
                "edge_bps": plan.trade_idea.edge_bps,
                "confidence": plan.trade_idea.confidence,
                "fair_probability": plan.trade_idea.fair_probability,
            }
        return order

    def resolve_all(
        self,
        resolutions: dict[str, float],
        winning_outcomes: dict[str, str],
    ) -> list[BacktestTradeResult]:
        """
        Close all open positions at resolution prices.

        Args:
            resolutions: token_id → payout (1.0 win, 0.0 loss)
            winning_outcomes: condition_id → name of the winning outcome
        """
        results: list[BacktestTradeResult] = []

        for token_id, pos in list(self._positions.items()):
            if pos.size_tokens <= 0:
                continue

            payout = resolutions.get(token_id, 0.0)
            proceeds = pos.size_tokens * payout
            cost = pos.cost_basis_usdc
            pnl = proceeds - cost

            self._cash += proceeds
            self._realized_pnl += pnl
            pos.realized_pnl += pnl
            pos.size_tokens = 0
            pos.cost_basis_usdc = 0.0

            meta = self._order_meta.get(token_id, {})
            results.append(
                BacktestTradeResult(
                    condition_id=pos.condition_id,
                    question=meta.get("question", ""),
                    category=meta.get("category", pos.category),
                    outcome_traded=pos.outcome,
                    winning_outcome=winning_outcomes.get(pos.condition_id, ""),
                    won=payout == 1.0,
                    entry_price=pos.avg_entry_price,
                    resolution_price=payout,
                    size_usdc=cost,
                    pnl=pnl,
                    edge_bps=meta.get("edge_bps", 0.0),
                    confidence=meta.get("confidence", 0.0),
                    fair_probability=meta.get("fair_probability", 0.0),
                )
            )

        return results
