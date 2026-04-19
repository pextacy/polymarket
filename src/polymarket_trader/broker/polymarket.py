from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from loguru import logger
from py_clob_client.client import ClobClient as PyClobClient
from py_clob_client.clob_types import ApiCreds, OrderArgs, OrderType as ClobOrderType
from py_clob_client.constants import POLYGON

from ..config import Settings
from ..connectors.clob import ClobClient
from ..models.broker import (
    FillRecord,
    OrderRecord,
    OrderStatus,
    PortfolioState,
    PositionState,
)
from ..models.trade import ExecutionPlan, OrderType, Side
from .base import BaseBroker


class PolymarketBroker(BaseBroker):
    def __init__(
        self,
        settings: Settings,
        clob_client: ClobClient,
    ) -> None:
        settings.require_live_keys()
        self._settings = settings
        self._clob_http = clob_client
        self._py_client = PyClobClient(
            host=settings.clob_base_url,
            chain_id=POLYGON,
            private_key=settings.polymarket_private_key,
            signature_type=2,
            funder=settings.polymarket_proxy_address,
        )
        self._api_creds: Optional[ApiCreds] = None
        self._open_orders: dict[str, OrderRecord] = {}

    async def _ensure_creds(self) -> None:
        if self._api_creds is not None:
            return
        try:
            self._api_creds = self._py_client.create_or_derive_api_creds()
            self._py_client.set_api_creds(self._api_creds)
            logger.info("Polymarket API credentials derived")
        except Exception as e:
            raise RuntimeError(f"Failed to derive Polymarket API credentials: {e}") from e

    async def preflight(self) -> None:
        blocked = await self._clob_http.check_geoblock()
        if blocked:
            raise RuntimeError(
                "Geoblock check failed: live trading is not available in this region. "
                "Switch to paper mode."
            )
        await self._ensure_creds()
        logger.info("Polymarket preflight passed")

    async def submit(self, plan: ExecutionPlan, run_id: str) -> OrderRecord:
        await self._ensure_creds()

        order_id = str(uuid.uuid4())

        side_str = "BUY" if plan.side == Side.BUY else "SELL"

        if plan.order_type == OrderType.FOK:
            clob_order_type = ClobOrderType.FOK
        elif plan.order_type == OrderType.FAK:
            clob_order_type = ClobOrderType.FAK
        else:
            clob_order_type = ClobOrderType.GTC

        order_args = OrderArgs(
            token_id=plan.token_id,
            price=plan.limit_price,
            size=plan.size_usdc / plan.limit_price,
            side=side_str,
        )

        try:
            signed_order = self._py_client.create_order(order_args)
            response = self._py_client.post_order(signed_order, clob_order_type)

            exchange_order_id = response.get("orderID") or response.get("id")
            status_str = response.get("status", "")
            status = OrderStatus.PENDING

            if status_str in ("matched", "filled"):
                status = OrderStatus.FILLED
            elif status_str == "cancelled":
                status = OrderStatus.CANCELLED
            elif status_str == "expired":
                status = OrderStatus.EXPIRED

            record = OrderRecord(
                order_id=order_id,
                run_id=run_id,
                condition_id=plan.trade_idea.condition_id,
                token_id=plan.token_id,
                outcome=plan.trade_idea.outcome,
                side=plan.side,
                order_type=plan.order_type,
                size_usdc=plan.size_usdc,
                limit_price=plan.limit_price,
                status=status,
                exchange_order_id=exchange_order_id,
                raw_response=response,
            )

            if status == OrderStatus.PENDING:
                self._open_orders[order_id] = record

            logger.info(
                "Live ORDER: {} {} ${:.2f} @ {:.4f} → status={}",
                plan.side.value,
                plan.trade_idea.outcome,
                plan.size_usdc,
                plan.limit_price,
                status_str,
            )
            return record

        except Exception as e:
            logger.error("Live order submission failed for {}: {}", plan.token_id, e)
            record = OrderRecord(
                order_id=order_id,
                run_id=run_id,
                condition_id=plan.trade_idea.condition_id,
                token_id=plan.token_id,
                outcome=plan.trade_idea.outcome,
                side=plan.side,
                order_type=plan.order_type,
                size_usdc=plan.size_usdc,
                limit_price=plan.limit_price,
                status=OrderStatus.REJECTED,
                raw_response={"error": str(e)},
            )
            return record

    async def get_portfolio(self) -> PortfolioState:
        await self._ensure_creds()
        try:
            positions_raw = self._py_client.get_positions()
            positions: dict[str, PositionState] = {}
            for p in positions_raw:
                token_id = p.get("asset_id", "")
                size = float(p.get("size", 0))
                avg_price = float(p.get("average_price", 0))
                positions[token_id] = PositionState(
                    condition_id=p.get("condition_id", ""),
                    token_id=token_id,
                    outcome=p.get("outcome", ""),
                    size_tokens=size,
                    avg_entry_price=avg_price,
                    cost_basis_usdc=size * avg_price,
                )

            balance_raw = self._py_client.get_balance_allowance()
            cash = float(balance_raw.get("balance", 0))

            return PortfolioState(
                cash_usdc=cash,
                positions=positions,
            )
        except Exception as e:
            logger.error("Failed to fetch live portfolio: {}", e)
            return PortfolioState(cash_usdc=0.0)

    async def open_order_count(self) -> int:
        await self._ensure_creds()
        try:
            orders = self._py_client.get_orders()
            return len([o for o in orders if o.get("status") == "live"])
        except Exception as e:
            logger.error("Failed to fetch open orders: {}", e)
            return len(self._open_orders)
