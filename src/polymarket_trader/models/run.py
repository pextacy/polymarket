from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class RunStatus(str, Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"


class RunRecord(BaseModel):
    run_id: str
    trading_mode: str
    status: RunStatus = RunStatus.RUNNING
    markets_scanned: int = 0
    opportunities_found: int = 0
    trades_planned: int = 0
    trades_executed: int = 0
    realized_pnl: float = 0.0
    error_count: int = 0
    last_error: Optional[str] = None
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None

    @property
    def duration_seconds(self) -> Optional[float]:
        if self.completed_at is None:
            return None
        return (self.completed_at - self.started_at).total_seconds()
