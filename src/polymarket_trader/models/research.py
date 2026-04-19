from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, HttpUrl


class EvidenceItem(BaseModel):
    title: str
    url: str
    snippet: str
    source: str
    published_at: Optional[datetime] = None
    score: float = 0.0
    full_text: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)

    def is_fresh(self, max_age_hours: float = 72.0) -> bool:
        if self.published_at is None:
            return True
        age = (datetime.utcnow() - self.published_at).total_seconds() / 3600
        return age <= max_age_hours
