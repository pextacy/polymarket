from __future__ import annotations

from abc import ABC, abstractmethod

from ..models.broker import FillRecord, OrderRecord, PortfolioState
from ..models.trade import ExecutionPlan


class BaseBroker(ABC):
    @abstractmethod
    async def submit(self, plan: ExecutionPlan, run_id: str) -> OrderRecord:
        ...

    @abstractmethod
    async def get_portfolio(self) -> PortfolioState:
        ...

    @abstractmethod
    async def open_order_count(self) -> int:
        ...
