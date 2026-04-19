from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class RiskVerdictType(str, Enum):
    APPROVED = "approved"
    REJECTED = "rejected"


class RiskDecision(BaseModel):
    condition_id: str
    token_id: str
    verdict: RiskVerdictType
    reasons: list[str] = Field(default_factory=list)
    decided_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def approved(self) -> bool:
        return self.verdict == RiskVerdictType.APPROVED
