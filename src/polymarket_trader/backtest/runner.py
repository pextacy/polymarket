from __future__ import annotations

import asyncio
from typing import Optional

from loguru import logger

from ..config import Settings
from ..connectors.browser import LightpandaClient
from ..connectors.clob import ClobClient
from ..connectors.gamma import GammaClient
from ..connectors.search import SearXNGClient
from ..intelligence.forecaster import Forecaster
from ..intelligence.ranker import Ranker
from ..models.broker import OrderStatus
from ..models.market import MarketSnapshot
from ..persistence.store import TradeStore
from ..providers.openai_compatible import OpenAICompatibleProvider
from ..research.pipeline import ResearchPipeline
from ..risk.engine import RiskEngine
from ..strategy.planner import ExecutionPlanner
from ..strategy.scorer import OpportunityScorer
from .broker import BacktestBroker
from .models import BacktestSummary, BacktestTradeResult


def _build_resolutions(market: MarketSnapshot) -> tuple[dict[str, float], str]:
    """
    Return (token_id → payout, winning_outcome_name) for a resolved market.
    Winner token pays 1.0; losers pay 0.0.
    """
    resolutions: dict[str, float] = {}
    winning_outcome = ""
    for token in market.tokens:
        payout = 1.0 if token.winner else 0.0
        resolutions[token.token_id] = payout
        if token.winner:
            winning_outcome = token.outcome
    return resolutions, winning_outcome


class BacktestRunner:
    """
    Runs the full research → forecast → score → plan → risk pipeline
    against recently resolved Polymarket markets and measures hypothetical PnL.

    Resolution is deterministic: winning tokens pay $1.00, losing tokens pay $0.00.
    No real orders are placed.
    """

    def __init__(self, settings: Settings) -> None:
        self._s = settings
        self._provider = OpenAICompatibleProvider(
            **settings.llm_client_config(),
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

    async def run(
        self,
        days_back: int = 30,
        initial_cash: float = 10_000.0,
        min_volume: float = 5_000.0,
        market_limit: int = 50,
        use_evidence_cache: bool = True,
    ) -> BacktestSummary:
        """
        Run a backtest over recently resolved markets.

        Args:
            days_back: How far back to look for resolved markets.
            initial_cash: Starting portfolio cash in USDC.
            min_volume: Minimum 24h volume or liquidity to include a market.
            market_limit: Maximum number of resolved markets to test against.
            use_evidence_cache: Re-use evidence stored in DB if available.
        """
        await self._store.init()
        broker = BacktestBroker(initial_cash=initial_cash)

        logger.info(
            "Backtest: fetching resolved markets ({}d back, limit={}, min_vol=${:.0f})",
            days_back,
            market_limit,
            min_volume,
        )
        resolved_markets = await self._gamma.fetch_resolved_markets(
            days_back=days_back,
            min_volume=min_volume,
            limit=market_limit,
        )

        if not resolved_markets:
            logger.warning("Backtest: no resolved markets found — check Gamma API connectivity")
            return BacktestSummary(
                initial_cash=initial_cash,
                final_cash=initial_cash,
                total_markets_evaluated=0,
                total_trades=0,
                winning_trades=0,
                losing_trades=0,
                skipped_no_edge=0,
                skipped_risk=0,
                skipped_no_plan=0,
                forecast_failures=0,
            )

        logger.info("Backtest: evaluating {} resolved markets", len(resolved_markets))

        counters = {
            "no_edge": 0,
            "no_plan": 0,
            "risk_rejected": 0,
            "forecast_fail": 0,
        }

        sem = asyncio.Semaphore(3)
        run_id = "backtest"
        all_resolutions: dict[str, float] = {}
        winning_outcomes: dict[str, str] = {}

        for market in resolved_markets:
            token_payouts, winner = _build_resolutions(market)
            all_resolutions.update(token_payouts)
            winning_outcomes[market.condition_id] = winner

        async def _process(market: MarketSnapshot) -> None:
            async with sem:
                try:
                    if use_evidence_cache:
                        evidence = await self._store.get_cached_evidence(
                            market.condition_id, max_age_hours=168.0
                        )
                        if not evidence:
                            evidence = await self._research.research(market)
                            if evidence:
                                await self._store.save_evidence(run_id, market.condition_id, evidence)
                    else:
                        evidence = await self._research.research(market)

                    forecast = await self._forecaster.forecast(market, evidence)
                    if forecast is None:
                        counters["forecast_fail"] += 1
                        return

                    score = self._scorer.score(
                        market, forecast, min_edge_bps=self._s.scan_min_edge_bps
                    )
                    if score is None:
                        counters["no_edge"] += 1
                        return

                    portfolio = await broker.get_portfolio()
                    plan = self._planner.plan(score, market, portfolio.cash_usdc)
                    if plan is None:
                        counters["no_plan"] += 1
                        return

                    open_orders = await broker.open_order_count()
                    decision = self._risk.evaluate(plan, market, portfolio, open_orders)
                    if not decision.approved:
                        counters["risk_rejected"] += 1
                        return

                    order = await broker.submit(plan, run_id)
                    if order.status == OrderStatus.FILLED:
                        self._risk.record_win(market.condition_id)
                    else:
                        self._risk.record_loss(market.condition_id)

                except Exception as e:
                    logger.error(
                        "Backtest: error processing {}: {}", market.condition_id, e
                    )
                    counters["forecast_fail"] += 1

        await asyncio.gather(*[_process(m) for m in resolved_markets])

        trade_results = broker.resolve_all(all_resolutions, winning_outcomes)
        final_portfolio = await broker.get_portfolio()

        winning = sum(1 for t in trade_results if t.won)
        losing = sum(1 for t in trade_results if not t.won)

        logger.info(
            "Backtest complete: {} trades, {}/{} win/loss, PnL=${:.2f}, ROI={:.1f}%",
            len(trade_results),
            winning,
            losing,
            sum(t.pnl for t in trade_results),
            sum(t.pnl for t in trade_results) / initial_cash * 100,
        )

        return BacktestSummary(
            initial_cash=initial_cash,
            final_cash=final_portfolio.cash_usdc,
            total_markets_evaluated=len(resolved_markets),
            total_trades=len(trade_results),
            winning_trades=winning,
            losing_trades=losing,
            skipped_no_edge=counters["no_edge"],
            skipped_risk=counters["risk_rejected"],
            skipped_no_plan=counters["no_plan"],
            forecast_failures=counters["forecast_fail"],
            trades=trade_results,
        )
