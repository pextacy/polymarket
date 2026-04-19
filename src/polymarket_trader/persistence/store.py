from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Optional

from loguru import logger
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, delete, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from ..models.broker import FillRecord, OrderRecord, PortfolioState, PositionState
from ..models.forecast import Forecast
from ..models.market import MarketSnapshot
from ..models.research import EvidenceItem
from ..models.risk import RiskDecision, RiskVerdictType
from ..models.run import RunRecord
from ..models.trade import ExecutionPlan


class Base(DeclarativeBase):
    pass


class RunRow(Base):
    __tablename__ = "runs"

    run_id = Column(String, primary_key=True)
    trading_mode = Column(String, nullable=False)
    status = Column(String, nullable=False, default="running")
    markets_scanned = Column(Integer, default=0)
    opportunities_found = Column(Integer, default=0)
    trades_planned = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)
    realized_pnl = Column(Float, default=0.0)
    error_count = Column(Integer, default=0)
    last_error = Column(Text, nullable=True)
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime, nullable=True)


class MarketSnapshotRow(Base):
    __tablename__ = "market_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    question = Column(Text, nullable=False)
    category = Column(String, nullable=False)
    volume_24h = Column(Float, default=0.0)
    liquidity = Column(Float, default=0.0)
    best_bid = Column(Float, default=0.0)
    best_ask = Column(Float, default=1.0)
    fetched_at = Column(DateTime, nullable=False)
    raw_json = Column(Text, nullable=True)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    title = Column(Text, nullable=False)
    url = Column(Text, nullable=False)
    snippet = Column(Text, nullable=False)
    source = Column(String, nullable=False)
    published_at = Column(DateTime, nullable=True)
    score = Column(Float, default=0.0)
    fetched_at = Column(DateTime, nullable=False)


class ForecastRow(Base):
    __tablename__ = "forecasts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    confidence = Column(Float, nullable=False)
    rationale = Column(Text, nullable=False)
    model_used = Column(String, nullable=False)
    outcomes_json = Column(Text, nullable=False)
    sources_json = Column(Text, nullable=False)
    created_at = Column(DateTime, nullable=False)


class ExecutionPlanRow(Base):
    __tablename__ = "execution_plans"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    side = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    size_usdc = Column(Float, nullable=False)
    limit_price = Column(Float, nullable=False)
    estimated_fill_price = Column(Float, nullable=False)
    estimated_slippage_bps = Column(Float, nullable=False)
    edge_bps = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    fair_probability = Column(Float, nullable=False)
    planned_at = Column(DateTime, nullable=False)


class RiskEventRow(Base):
    __tablename__ = "risk_events"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=False)
    verdict = Column(String, nullable=False)
    reasons_json = Column(Text, nullable=False)
    decided_at = Column(DateTime, nullable=False)


class PositionRow(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=False, index=True)
    outcome = Column(String, nullable=False)
    category = Column(String, nullable=False)
    size_tokens = Column(Float, nullable=False)
    avg_entry_price = Column(Float, nullable=False)
    cost_basis_usdc = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    snapshotted_at = Column(DateTime, nullable=False)


class PnLRow(Base):
    __tablename__ = "pnl_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    cash_usdc = Column(Float, nullable=False)
    realized_pnl = Column(Float, nullable=False)
    daily_loss = Column(Float, nullable=False)
    open_position_count = Column(Integer, nullable=False)
    snapshotted_at = Column(DateTime, nullable=False)


class ErrorRow(Base):
    __tablename__ = "errors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=True, index=True)
    stage = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    occurred_at = Column(DateTime, nullable=False)


class OrderRow(Base):
    __tablename__ = "orders"

    order_id = Column(String, primary_key=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    side = Column(String, nullable=False)
    order_type = Column(String, nullable=False)
    size_usdc = Column(Float, nullable=False)
    limit_price = Column(Float, nullable=False)
    status = Column(String, nullable=False)
    exchange_order_id = Column(String, nullable=True)
    submitted_at = Column(DateTime, nullable=False)
    raw_response = Column(Text, nullable=True)


class FillRow(Base):
    __tablename__ = "fills"

    fill_id = Column(String, primary_key=True)
    order_id = Column(String, nullable=False, index=True)
    run_id = Column(String, nullable=False, index=True)
    condition_id = Column(String, nullable=False, index=True)
    token_id = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    side = Column(String, nullable=False)
    filled_size_usdc = Column(Float, nullable=False)
    fill_price = Column(Float, nullable=False)
    fee_usdc = Column(Float, default=0.0)
    filled_at = Column(DateTime, nullable=False)


class TradeStore:
    def __init__(self, database_url: str) -> None:
        self._engine = create_async_engine(database_url, echo=False)
        self._session_factory = async_sessionmaker(self._engine, expire_on_commit=False)

    async def init(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database initialized")

    # ── Run ──────────────────────────────────────────────────────────────────────

    async def save_run(self, run: RunRecord) -> None:
        async with self._session_factory() as session:
            row = RunRow(
                run_id=run.run_id,
                trading_mode=run.trading_mode,
                status=run.status.value,
                markets_scanned=run.markets_scanned,
                opportunities_found=run.opportunities_found,
                trades_planned=run.trades_planned,
                trades_executed=run.trades_executed,
                realized_pnl=run.realized_pnl,
                error_count=run.error_count,
                last_error=run.last_error,
                started_at=run.started_at,
                completed_at=run.completed_at,
            )
            await session.merge(row)
            await session.commit()

    async def update_run(self, run: RunRecord) -> None:
        async with self._session_factory() as session:
            await session.execute(
                update(RunRow)
                .where(RunRow.run_id == run.run_id)
                .values(
                    status=run.status.value,
                    markets_scanned=run.markets_scanned,
                    opportunities_found=run.opportunities_found,
                    trades_planned=run.trades_planned,
                    trades_executed=run.trades_executed,
                    realized_pnl=run.realized_pnl,
                    error_count=run.error_count,
                    last_error=run.last_error,
                    completed_at=run.completed_at,
                )
            )
            await session.commit()

    async def get_runs(self, limit: int = 20) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RunRow).order_by(RunRow.started_at.desc()).limit(limit)
            )
            return [
                {
                    "run_id": r.run_id,
                    "trading_mode": r.trading_mode,
                    "status": r.status,
                    "markets_scanned": r.markets_scanned,
                    "opportunities_found": r.opportunities_found,
                    "trades_planned": r.trades_planned,
                    "trades_executed": r.trades_executed,
                    "realized_pnl": r.realized_pnl,
                    "error_count": r.error_count,
                    "started_at": r.started_at,
                    "completed_at": r.completed_at,
                }
                for r in result.scalars().all()
            ]

    # ── Market Snapshots ─────────────────────────────────────────────────────────

    async def save_market_snapshot(self, run_id: str, market: MarketSnapshot) -> None:
        async with self._session_factory() as session:
            row = MarketSnapshotRow(
                run_id=run_id,
                condition_id=market.condition_id,
                question=market.question,
                category=market.category,
                volume_24h=market.volume_24h,
                liquidity=market.liquidity,
                best_bid=market.best_bid,
                best_ask=market.best_ask,
                fetched_at=market.fetched_at,
                raw_json=market.model_dump_json(),
            )
            session.add(row)
            await session.commit()

    # ── Evidence ─────────────────────────────────────────────────────────────────

    async def save_evidence(self, run_id: str, condition_id: str, items: list[EvidenceItem]) -> None:
        async with self._session_factory() as session:
            for item in items:
                row = EvidenceRow(
                    run_id=run_id,
                    condition_id=condition_id,
                    title=item.title,
                    url=item.url,
                    snippet=item.snippet,
                    source=item.source,
                    published_at=item.published_at,
                    score=item.score,
                    fetched_at=item.fetched_at,
                )
                session.add(row)
            await session.commit()

    async def get_cached_evidence(
        self, condition_id: str, max_age_hours: float = 6.0
    ) -> list[EvidenceItem]:
        """Return fresh evidence from a previous run, avoiding redundant research."""
        cutoff = datetime.utcnow() - timedelta(hours=max_age_hours)
        async with self._session_factory() as session:
            result = await session.execute(
                select(EvidenceRow)
                .where(
                    EvidenceRow.condition_id == condition_id,
                    EvidenceRow.fetched_at >= cutoff,
                )
                .order_by(EvidenceRow.score.desc())
                .limit(30)
            )
            rows = result.scalars().all()
            if not rows:
                return []
            return [
                EvidenceItem(
                    title=r.title,
                    url=r.url,
                    snippet=r.snippet,
                    source=r.source,
                    published_at=r.published_at,
                    score=r.score,
                    fetched_at=r.fetched_at,
                )
                for r in rows
            ]

    async def get_evidence_for_run(self, run_id: str, condition_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(EvidenceRow)
                .where(EvidenceRow.run_id == run_id, EvidenceRow.condition_id == condition_id)
                .order_by(EvidenceRow.score.desc())
            )
            return [
                {
                    "title": r.title,
                    "url": r.url,
                    "source": r.source,
                    "published_at": r.published_at,
                    "score": r.score,
                }
                for r in result.scalars().all()
            ]

    # ── Forecasts ────────────────────────────────────────────────────────────────

    async def save_forecast(self, run_id: str, forecast: Forecast) -> None:
        async with self._session_factory() as session:
            row = ForecastRow(
                run_id=run_id,
                condition_id=forecast.condition_id,
                confidence=forecast.confidence,
                rationale=forecast.rationale,
                model_used=forecast.model_used,
                outcomes_json=json.dumps([o.model_dump() for o in forecast.outcomes]),
                sources_json=json.dumps(forecast.sources_used),
                created_at=forecast.created_at,
            )
            session.add(row)
            await session.commit()

    async def get_forecasts_for_run(self, run_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ForecastRow)
                .where(ForecastRow.run_id == run_id)
                .order_by(ForecastRow.confidence.desc())
            )
            return [
                {
                    "condition_id": r.condition_id,
                    "confidence": r.confidence,
                    "rationale": r.rationale[:200],
                    "model_used": r.model_used,
                    "outcomes": json.loads(r.outcomes_json),
                    "created_at": r.created_at,
                }
                for r in result.scalars().all()
            ]

    # ── Execution Plans ───────────────────────────────────────────────────────────

    async def save_execution_plan(self, run_id: str, plan: ExecutionPlan) -> None:
        async with self._session_factory() as session:
            row = ExecutionPlanRow(
                run_id=run_id,
                condition_id=plan.trade_idea.condition_id,
                token_id=plan.token_id,
                outcome=plan.trade_idea.outcome,
                side=plan.side.value,
                order_type=plan.order_type.value,
                size_usdc=plan.size_usdc,
                limit_price=plan.limit_price,
                estimated_fill_price=plan.estimated_fill_price,
                estimated_slippage_bps=plan.estimated_slippage_bps,
                edge_bps=plan.trade_idea.edge_bps,
                confidence=plan.trade_idea.confidence,
                fair_probability=plan.trade_idea.fair_probability,
                planned_at=plan.planned_at,
            )
            session.add(row)
            await session.commit()

    async def get_execution_plans_for_run(self, run_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(ExecutionPlanRow)
                .where(ExecutionPlanRow.run_id == run_id)
                .order_by(ExecutionPlanRow.planned_at)
            )
            return [
                {
                    "condition_id": r.condition_id,
                    "outcome": r.outcome,
                    "side": r.side,
                    "size_usdc": r.size_usdc,
                    "limit_price": r.limit_price,
                    "edge_bps": r.edge_bps,
                    "confidence": r.confidence,
                    "fair_probability": r.fair_probability,
                    "planned_at": r.planned_at,
                }
                for r in result.scalars().all()
            ]

    # ── Risk Events ───────────────────────────────────────────────────────────────

    async def save_risk_event(self, run_id: str, decision: RiskDecision) -> None:
        async with self._session_factory() as session:
            row = RiskEventRow(
                run_id=run_id,
                condition_id=decision.condition_id,
                token_id=decision.token_id,
                verdict=decision.verdict.value,
                reasons_json=json.dumps(decision.reasons),
                decided_at=decision.decided_at,
            )
            session.add(row)
            await session.commit()

    async def get_risk_events_for_run(self, run_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(RiskEventRow)
                .where(RiskEventRow.run_id == run_id)
                .order_by(RiskEventRow.decided_at)
            )
            return [
                {
                    "condition_id": r.condition_id,
                    "verdict": r.verdict,
                    "reasons": json.loads(r.reasons_json),
                    "decided_at": r.decided_at,
                }
                for r in result.scalars().all()
            ]

    # ── Positions ─────────────────────────────────────────────────────────────────

    async def save_position_snapshot(self, run_id: str, positions: dict[str, PositionState]) -> None:
        async with self._session_factory() as session:
            await session.execute(
                delete(PositionRow).where(PositionRow.run_id == run_id)
            )
            now = datetime.utcnow()
            for pos in positions.values():
                if pos.size_tokens <= 0:
                    continue
                row = PositionRow(
                    run_id=run_id,
                    condition_id=pos.condition_id,
                    token_id=pos.token_id,
                    outcome=pos.outcome,
                    category=pos.category,
                    size_tokens=pos.size_tokens,
                    avg_entry_price=pos.avg_entry_price,
                    cost_basis_usdc=pos.cost_basis_usdc,
                    realized_pnl=pos.realized_pnl,
                    snapshotted_at=now,
                )
                session.add(row)
            await session.commit()

    async def get_positions_for_run(self, run_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PositionRow).where(PositionRow.run_id == run_id)
            )
            return [
                {
                    "condition_id": r.condition_id,
                    "outcome": r.outcome,
                    "category": r.category,
                    "size_tokens": r.size_tokens,
                    "avg_entry_price": r.avg_entry_price,
                    "cost_basis_usdc": r.cost_basis_usdc,
                    "realized_pnl": r.realized_pnl,
                }
                for r in result.scalars().all()
            ]

    # ── PnL Snapshots ─────────────────────────────────────────────────────────────

    async def save_pnl_snapshot(self, run_id: str, portfolio: PortfolioState) -> None:
        async with self._session_factory() as session:
            row = PnLRow(
                run_id=run_id,
                cash_usdc=portfolio.cash_usdc,
                realized_pnl=portfolio.realized_pnl,
                daily_loss=portfolio.daily_loss,
                open_position_count=portfolio.open_position_count(),
                snapshotted_at=datetime.utcnow(),
            )
            session.add(row)
            await session.commit()

    async def get_pnl_history(self, run_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(PnLRow)
                .where(PnLRow.run_id == run_id)
                .order_by(PnLRow.snapshotted_at)
            )
            return [
                {
                    "cash_usdc": r.cash_usdc,
                    "realized_pnl": r.realized_pnl,
                    "daily_loss": r.daily_loss,
                    "open_position_count": r.open_position_count,
                    "snapshotted_at": r.snapshotted_at,
                }
                for r in result.scalars().all()
            ]

    # ── Errors ────────────────────────────────────────────────────────────────────

    async def save_error(
        self, run_id: str, stage: str, message: str, condition_id: Optional[str] = None
    ) -> None:
        async with self._session_factory() as session:
            row = ErrorRow(
                run_id=run_id,
                condition_id=condition_id,
                stage=stage,
                message=message[:2000],
                occurred_at=datetime.utcnow(),
            )
            session.add(row)
            await session.commit()

    async def get_errors(self, run_id: Optional[str] = None, limit: int = 50) -> list[dict]:
        async with self._session_factory() as session:
            q = select(ErrorRow).order_by(ErrorRow.occurred_at.desc()).limit(limit)
            if run_id:
                q = q.where(ErrorRow.run_id == run_id)
            result = await session.execute(q)
            return [
                {
                    "run_id": r.run_id,
                    "condition_id": r.condition_id,
                    "stage": r.stage,
                    "message": r.message,
                    "occurred_at": r.occurred_at,
                }
                for r in result.scalars().all()
            ]

    # ── Orders & Fills ────────────────────────────────────────────────────────────

    async def save_order(self, order: OrderRecord) -> None:
        async with self._session_factory() as session:
            row = OrderRow(
                order_id=order.order_id,
                run_id=order.run_id,
                condition_id=order.condition_id,
                token_id=order.token_id,
                outcome=order.outcome,
                side=order.side.value,
                order_type=order.order_type.value,
                size_usdc=order.size_usdc,
                limit_price=order.limit_price,
                status=order.status.value,
                exchange_order_id=order.exchange_order_id,
                submitted_at=order.submitted_at,
                raw_response=json.dumps(order.raw_response) if order.raw_response else None,
            )
            await session.merge(row)
            await session.commit()

    async def save_fill(self, fill: FillRecord) -> None:
        async with self._session_factory() as session:
            row = FillRow(
                fill_id=fill.fill_id,
                order_id=fill.order_id,
                run_id=fill.run_id,
                condition_id=fill.condition_id,
                token_id=fill.token_id,
                outcome=fill.outcome,
                side=fill.side.value,
                filled_size_usdc=fill.filled_size_usdc,
                fill_price=fill.fill_price,
                fee_usdc=fill.fee_usdc,
                filled_at=fill.filled_at,
            )
            session.add(row)
            await session.commit()

    async def get_fills_for_run(self, run_id: str) -> list[dict]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(FillRow)
                .where(FillRow.run_id == run_id)
                .order_by(FillRow.filled_at.desc())
            )
            return [
                {
                    "fill_id": r.fill_id,
                    "condition_id": r.condition_id,
                    "outcome": r.outcome,
                    "side": r.side,
                    "filled_size_usdc": r.filled_size_usdc,
                    "fill_price": r.fill_price,
                    "filled_at": r.filled_at,
                }
                for r in result.scalars().all()
            ]

    # ── Reconciliation ────────────────────────────────────────────────────────────

    async def reconcile_positions(self, run_id: str) -> list[dict]:
        """Compare fills vs persisted positions and surface any drift."""
        fills = await self.get_fills_for_run(run_id)
        positions = await self.get_positions_for_run(run_id)

        fill_by_condition: dict[str, dict] = {}
        for f in fills:
            cid = f["condition_id"]
            if cid not in fill_by_condition:
                fill_by_condition[cid] = {"buys": 0.0, "sells": 0.0}
            if f["side"] == "BUY":
                fill_by_condition[cid]["buys"] += f["filled_size_usdc"]
            else:
                fill_by_condition[cid]["sells"] += f["filled_size_usdc"]

        pos_by_condition: dict[str, float] = {
            p["condition_id"]: p["cost_basis_usdc"] for p in positions
        }

        discrepancies = []
        for cid, flows in fill_by_condition.items():
            net_invested = flows["buys"] - flows["sells"]
            pos_cost = pos_by_condition.get(cid, 0.0)
            drift = abs(net_invested - pos_cost)
            if drift > 0.01:
                discrepancies.append(
                    {
                        "condition_id": cid,
                        "net_fills_usdc": round(net_invested, 4),
                        "position_cost_basis_usdc": round(pos_cost, 4),
                        "drift_usdc": round(drift, 4),
                    }
                )
        return discrepancies
