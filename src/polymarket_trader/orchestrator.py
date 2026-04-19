from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Optional

from loguru import logger

from .broker.base import BaseBroker
from .broker.paper import PaperBroker
from .config import Settings, TradingMode
from .connectors.browser import LightpandaClient
from .connectors.clob import ClobClient
from .connectors.gamma import GammaClient
from .connectors.search import SearXNGClient
from .discovery.scanner import MarketScanner
from .intelligence.forecaster import Forecaster
from .intelligence.ranker import Ranker
from .models.forecast import OpportunityScore
from .models.market import MarketSnapshot
from .models.run import RunRecord, RunStatus
from .persistence.store import TradeStore
from .providers.openrouter import OpenRouterProvider
from .research.pipeline import ResearchPipeline
from .risk.engine import RiskEngine
from .strategy.planner import ExecutionPlanner
from .strategy.scorer import OpportunityScorer


class Orchestrator:
    def __init__(self, settings: Settings) -> None:
        self._s = settings

        self._provider = OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
            default_model=settings.llm_model,
        )

        self._gamma = GammaClient(settings.gamma_base_url)
        self._clob = ClobClient(settings.clob_base_url)
        self._search = SearXNGClient(
            base_url=settings.searxng_base_url,
            timeout=settings.searxng_timeout_seconds,
        )
        self._browser = LightpandaClient(
            ws_url=settings.lightpanda_ws_url,
            timeout=settings.lightpanda_timeout_seconds,
            max_page_bytes=settings.lightpanda_max_page_bytes,
        )

        self._ranker = Ranker(self._provider, model=settings.ranking_model)
        self._scanner = MarketScanner(
            self._gamma, self._clob, self._ranker, settings
        )
        self._research = ResearchPipeline(
            search=self._search,
            browser=self._browser,
            provider=self._provider,
            extraction_model=settings.extraction_model,
            max_sources=settings.scan_max_research_sources,
        )
        self._forecaster = Forecaster(self._provider, model=settings.forecasting_model)
        self._scorer = OpportunityScorer()
        self._planner = ExecutionPlanner(settings)
        self._risk = RiskEngine(settings)
        self._store = TradeStore(settings.database_url)

        if settings.trading_mode == TradingMode.PAPER:
            self._broker: BaseBroker = PaperBroker(
                initial_cash=settings.paper_initial_cash,
                fill_slippage_bps=settings.paper_fill_slippage_bps,
            )
        else:
            from .broker.polymarket import PolymarketBroker
            self._broker = PolymarketBroker(settings, self._clob)

    async def run_once(self) -> RunRecord:
        run_id = str(uuid.uuid4())
        run = RunRecord(
            run_id=run_id,
            trading_mode=self._s.trading_mode.value,
        )

        await self._store.init()
        await self._store.save_run(run)

        if self._s.trading_mode == TradingMode.LIVE:
            from .broker.polymarket import PolymarketBroker
            assert isinstance(self._broker, PolymarketBroker)
            await self._broker.preflight()

        try:
            markets = await self._scanner.scan(top_n=20)
            run.markets_scanned = len(markets)
            await self._store.update_run(run)

            if not markets:
                logger.warning("No markets found in this scan cycle")
                run.status = RunStatus.COMPLETED
                await self._store.update_run(run)
                return run

            for market in markets:
                await self._store.save_market_snapshot(run_id, market)

            scores = await self._process_markets(run_id, run, markets)
            scores.sort(key=lambda s: s.final_score, reverse=True)

            run.opportunities_found = len(scores)
            await self._store.update_run(run)

            portfolio = await self._broker.get_portfolio()
            open_orders = await self._broker.open_order_count()

            for score in scores:
                market = next(
                    (m for m in markets if m.condition_id == score.condition_id), None
                )
                if market is None:
                    continue

                plan = self._planner.plan(
                    score, market, portfolio.cash_usdc
                )
                if plan is None:
                    continue

                run.trades_planned += 1

                decision = self._risk.evaluate(plan, market, portfolio, open_orders)
                if not decision.approved:
                    continue

                order = await self._broker.submit(plan, run_id)
                await self._store.save_order(order)

                from .models.broker import OrderStatus
                if order.status == OrderStatus.FILLED:
                    run.trades_executed += 1
                    open_orders += 1
                    portfolio = await self._broker.get_portfolio()

                    if isinstance(self._broker, PaperBroker):
                        fills = self._broker.get_fills()
                        for fill in fills[-1:]:
                            await self._store.save_fill(fill)

            run.status = RunStatus.COMPLETED
            run.completed_at = datetime.utcnow()

            portfolio = await self._broker.get_portfolio()
            run.realized_pnl = portfolio.realized_pnl

        except Exception as e:
            logger.exception("Orchestrator fatal error: {}", e)
            run.status = RunStatus.FAILED
            run.last_error = str(e)
            run.error_count += 1
            run.completed_at = datetime.utcnow()
        finally:
            await self._store.update_run(run)

        return run

    async def _process_markets(
        self,
        run_id: str,
        run: RunRecord,
        markets: list[MarketSnapshot],
    ) -> list[OpportunityScore]:
        sem = asyncio.Semaphore(3)
        scores: list[OpportunityScore] = []

        async def _process_one(market: MarketSnapshot) -> Optional[OpportunityScore]:
            async with sem:
                try:
                    evidence = await self._research.research(market)
                    await self._store.save_evidence(run_id, market.condition_id, evidence)

                    forecast = await self._forecaster.forecast(market, evidence)
                    if forecast is None:
                        return None

                    await self._store.save_forecast(run_id, forecast)

                    score = self._scorer.score(
                        market, forecast,
                        min_edge_bps=self._s.scan_min_edge_bps,
                    )
                    if score is None:
                        logger.debug(
                            "No edge for '{}' (condition_id={})",
                            market.question[:60],
                            market.condition_id,
                        )
                    return score
                except Exception as e:
                    logger.error("Processing failed for {}: {}", market.condition_id, e)
                    run.error_count += 1
                    await self._store.update_run(run)
                    return None

        results = await asyncio.gather(*[_process_one(m) for m in markets])
        for r in results:
            if r is not None:
                scores.append(r)

        return scores

    async def run_continuous(self) -> None:
        logger.info(
            "Starting continuous trading loop (mode={}, interval={}s)",
            self._s.trading_mode.value,
            self._s.scan_interval_seconds,
        )
        while True:
            run = await self.run_once()
            logger.info(
                "Cycle complete: run_id={} status={} markets={} executed={} pnl={:.2f}",
                run.run_id,
                run.status.value,
                run.markets_scanned,
                run.trades_executed,
                run.realized_pnl,
            )
            await asyncio.sleep(self._s.scan_interval_seconds)
