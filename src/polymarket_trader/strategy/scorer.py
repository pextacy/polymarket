from __future__ import annotations

from ..models.forecast import Forecast, OpportunityScore
from ..models.market import MarketSnapshot


class OpportunityScorer:
    def score(
        self,
        market: MarketSnapshot,
        forecast: Forecast,
        min_edge_bps: int = 200,
    ) -> OpportunityScore | None:
        best = forecast.best_outcome()
        if best is None:
            return None

        edge_bps = best.edge_bps
        if abs(edge_bps) < min_edge_bps:
            return None

        score = OpportunityScore(
            condition_id=market.condition_id,
            question=market.question,
            category=market.category,
            edge_bps=edge_bps,
            confidence=forecast.confidence,
            liquidity=market.liquidity,
            volume_24h=market.volume_24h,
            hours_to_expiry=market.hours_to_expiry,
            forecast=forecast,
        )
        score.compute_score()
        return score
