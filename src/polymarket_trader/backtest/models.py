from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BacktestTradeResult:
    condition_id: str
    question: str
    category: str
    outcome_traded: str
    winning_outcome: str
    won: bool
    entry_price: float
    resolution_price: float
    size_usdc: float
    pnl: float
    edge_bps: float
    confidence: float
    fair_probability: float

    @property
    def roi_pct(self) -> float:
        if self.size_usdc == 0:
            return 0.0
        return self.pnl / self.size_usdc * 100


@dataclass
class BacktestSummary:
    initial_cash: float
    final_cash: float
    total_markets_evaluated: int
    total_trades: int
    winning_trades: int
    losing_trades: int
    skipped_no_edge: int
    skipped_risk: int
    skipped_no_plan: int
    forecast_failures: int
    trades: list[BacktestTradeResult] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        if self.total_trades == 0:
            return 0.0
        return self.winning_trades / self.total_trades

    @property
    def total_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    @property
    def total_invested(self) -> float:
        return sum(t.size_usdc for t in self.trades)

    @property
    def roi_pct(self) -> float:
        if self.initial_cash == 0:
            return 0.0
        return self.total_pnl / self.initial_cash * 100

    @property
    def avg_edge_bps(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.edge_bps for t in self.trades) / len(self.trades)

    @property
    def avg_confidence(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.confidence for t in self.trades) / len(self.trades)

    @property
    def sharpe_ratio(self) -> float:
        if len(self.trades) < 2:
            return 0.0
        pnls = [t.pnl for t in self.trades]
        mean = sum(pnls) / len(pnls)
        variance = sum((p - mean) ** 2 for p in pnls) / len(pnls)
        std = math.sqrt(variance)
        if std == 0:
            return 0.0
        return mean / std * math.sqrt(len(pnls))

    @property
    def max_drawdown(self) -> float:
        if not self.trades:
            return 0.0
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in self.trades:
            cumulative += t.pnl
            if cumulative > peak:
                peak = cumulative
            dd = peak - cumulative
            if dd > max_dd:
                max_dd = dd
        return max_dd

    @property
    def avg_roi_per_trade(self) -> float:
        if not self.trades:
            return 0.0
        return sum(t.roi_pct for t in self.trades) / len(self.trades)
