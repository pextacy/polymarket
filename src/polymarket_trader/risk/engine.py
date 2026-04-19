from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger

from ..config import Settings
from ..models.broker import PortfolioState
from ..models.market import MarketSnapshot
from ..models.risk import RiskDecision, RiskVerdictType
from ..models.trade import ExecutionPlan, Side


class RiskEngine:
    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._loss_streak: dict[str, int] = defaultdict(int)
        self._cooldown_until: dict[str, datetime] = {}
        self._consecutive_global_losses: int = 0
        self._global_cooldown_until: Optional[datetime] = None

    def evaluate(
        self,
        plan: ExecutionPlan,
        market: MarketSnapshot,
        portfolio: PortfolioState,
        open_order_count: int,
    ) -> RiskDecision:
        condition_id = plan.trade_idea.condition_id
        token_id = plan.token_id
        reasons: list[str] = []

        if self._global_cooldown_until and datetime.utcnow() < self._global_cooldown_until:
            remaining = (self._global_cooldown_until - datetime.utcnow()).seconds
            reasons.append(f"global cooldown active for {remaining}s after repeated losses")
            return self._reject(condition_id, token_id, reasons)

        if condition_id in self._cooldown_until:
            until = self._cooldown_until[condition_id]
            if datetime.utcnow() < until:
                remaining = (until - datetime.utcnow()).seconds
                reasons.append(f"market cooldown active for {remaining}s")
                return self._reject(condition_id, token_id, reasons)

        age_seconds = (datetime.utcnow() - plan.planned_at).total_seconds()
        if age_seconds > self._s.risk_signal_staleness_seconds:
            reasons.append(
                f"stale signal: {age_seconds:.0f}s old, limit is {self._s.risk_signal_staleness_seconds}s"
            )
            return self._reject(condition_id, token_id, reasons)

        hours_to_expiry = market.hours_to_expiry
        if hours_to_expiry is not None and hours_to_expiry < self._s.risk_expiry_no_trade_hours:
            reasons.append(
                f"market expires in {hours_to_expiry:.1f}h, minimum is {self._s.risk_expiry_no_trade_hours}h"
            )
            return self._reject(condition_id, token_id, reasons)

        if plan.size_usdc > self._s.risk_max_notional_per_market:
            reasons.append(
                f"notional ${plan.size_usdc:.2f} exceeds per-market limit ${self._s.risk_max_notional_per_market:.2f}"
            )
            return self._reject(condition_id, token_id, reasons)

        midpoint_prices = {
            pos.token_id: pos.avg_entry_price
            for pos in portfolio.positions.values()
        }
        total_exposure = portfolio.total_exposure(midpoint_prices)
        if total_exposure + plan.size_usdc > self._s.risk_max_portfolio_exposure:
            reasons.append(
                f"portfolio exposure ${total_exposure + plan.size_usdc:.2f} would exceed limit ${self._s.risk_max_portfolio_exposure:.2f}"
            )
            return self._reject(condition_id, token_id, reasons)

        category = market.category
        cat_exposure = portfolio.category_exposure(category, midpoint_prices)
        if cat_exposure + plan.size_usdc > self._s.risk_max_category_exposure:
            reasons.append(
                f"category '{category}' exposure ${cat_exposure + plan.size_usdc:.2f} would exceed limit ${self._s.risk_max_category_exposure:.2f}"
            )
            return self._reject(condition_id, token_id, reasons)

        if portfolio.daily_loss >= self._s.risk_max_daily_loss:
            reasons.append(
                f"daily loss ${portfolio.daily_loss:.2f} reached limit ${self._s.risk_max_daily_loss:.2f}"
            )
            return self._reject(condition_id, token_id, reasons)

        if portfolio.open_position_count() >= self._s.risk_max_open_positions:
            reasons.append(
                f"open positions {portfolio.open_position_count()} reached limit {self._s.risk_max_open_positions}"
            )
            return self._reject(condition_id, token_id, reasons)

        if open_order_count >= self._s.risk_max_open_orders:
            reasons.append(
                f"open orders {open_order_count} reached limit {self._s.risk_max_open_orders}"
            )
            return self._reject(condition_id, token_id, reasons)

        logger.debug("Risk APPROVED: {} size=${:.2f}", condition_id, plan.size_usdc)
        return RiskDecision(
            condition_id=condition_id,
            token_id=token_id,
            verdict=RiskVerdictType.APPROVED,
        )

    def record_loss(self, condition_id: str) -> None:
        self._loss_streak[condition_id] += 1
        self._consecutive_global_losses += 1

        if self._loss_streak[condition_id] >= self._s.risk_cooldown_after_losses:
            until = datetime.utcnow() + timedelta(
                seconds=self._s.risk_cooldown_duration_seconds
            )
            self._cooldown_until[condition_id] = until
            logger.warning(
                "Market {} in cooldown until {} after {} consecutive losses",
                condition_id,
                until.isoformat(),
                self._loss_streak[condition_id],
            )

        if self._consecutive_global_losses >= self._s.risk_cooldown_after_losses * 2:
            until = datetime.utcnow() + timedelta(
                seconds=self._s.risk_cooldown_duration_seconds * 2
            )
            self._global_cooldown_until = until
            self._consecutive_global_losses = 0
            logger.warning("Global trading cooldown until {}", until.isoformat())

    def record_win(self, condition_id: str) -> None:
        self._loss_streak[condition_id] = 0
        self._consecutive_global_losses = max(0, self._consecutive_global_losses - 1)

    def _reject(
        self, condition_id: str, token_id: str, reasons: list[str]
    ) -> RiskDecision:
        for r in reasons:
            logger.info("Risk REJECTED {}: {}", condition_id, r)
        return RiskDecision(
            condition_id=condition_id,
            token_id=token_id,
            verdict=RiskVerdictType.REJECTED,
            reasons=reasons,
        )
