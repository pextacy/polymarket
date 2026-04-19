from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class OutcomeProbability(BaseModel):
    outcome: str
    token_id: str
    fair_probability: float
    market_price: float

    @property
    def edge_bps(self) -> float:
        return (self.fair_probability - self.market_price) * 10_000


class Forecast(BaseModel):
    condition_id: str
    confidence: float = Field(..., ge=0.0, le=1.0)
    rationale: str
    sources_used: list[str] = Field(default_factory=list)
    outcomes: list[OutcomeProbability] = Field(default_factory=list)
    model_used: str = ""
    created_at: datetime = Field(default_factory=datetime.utcnow)

    @field_validator("confidence")
    @classmethod
    def clamp_confidence(cls, v: float) -> float:
        return max(0.0, min(1.0, v))

    def best_outcome(self) -> Optional[OutcomeProbability]:
        if not self.outcomes:
            return None
        # Highest edge_bps first — naturally picks the most underpriced outcome (BUY side)
        return max(self.outcomes, key=lambda o: o.edge_bps)


class OpportunityScore(BaseModel):
    condition_id: str
    question: str
    category: str
    edge_bps: float
    confidence: float
    liquidity: float
    volume_24h: float
    hours_to_expiry: Optional[float]
    forecast: Forecast
    final_score: float = 0.0

    def compute_score(self) -> float:
        liquidity_factor = min(self.liquidity / 10_000, 1.0)
        expiry_factor = 1.0
        if self.hours_to_expiry is not None:
            if self.hours_to_expiry < 2:
                expiry_factor = 0.0
            elif self.hours_to_expiry < 24:
                expiry_factor = self.hours_to_expiry / 24
        self.final_score = (
            (self.edge_bps / 10_000) * self.confidence * liquidity_factor * expiry_factor
        )
        return self.final_score
