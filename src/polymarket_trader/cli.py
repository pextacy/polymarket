from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import click
from loguru import logger
from rich.console import Console
from rich.table import Table

from .config import TradingMode, get_settings
from .orchestrator import Orchestrator
from .persistence.store import TradeStore

console = Console()


def _setup_logging(log_level: str, log_file: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time} {level} {message}")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_file, level="DEBUG", rotation="50 MB", retention="30 days")


@click.group()
@click.option("--mode", type=click.Choice(["paper", "live"]), default=None)
@click.pass_context
def cli(ctx: click.Context, mode: str | None) -> None:
    """Autonomous Polymarket Trader"""
    ctx.ensure_object(dict)
    settings = get_settings()
    if mode is not None:
        settings.trading_mode = TradingMode(mode)
    _setup_logging(settings.log_level, settings.log_file)
    ctx.obj["settings"] = settings


@cli.command()
@click.option("--top", default=20, show_default=True, help="Number of markets to scan")
@click.pass_context
def scan(ctx: click.Context, top: int) -> None:
    """Scan active markets and show ranked opportunities."""
    settings = ctx.obj["settings"]

    async def _run() -> None:
        from .connectors.clob import ClobClient
        from .connectors.gamma import GammaClient
        from .intelligence.ranker import Ranker
        from .discovery.scanner import MarketScanner
        from .providers.openai_compatible import OpenAICompatibleProvider

        provider = OpenAICompatibleProvider(
            **settings.llm_client_config(),
            default_model=settings.ranking_model,
        )
        gamma = GammaClient(settings.gamma_base_url)
        clob = ClobClient(settings.clob_base_url)
        ranker = Ranker(provider, model=settings.ranking_model)
        scanner = MarketScanner(gamma, clob, ranker, settings)

        markets = await scanner.scan(top_n=top)

        table = Table(title=f"Top {len(markets)} Markets")
        table.add_column("Question", style="cyan", max_width=60)
        table.add_column("Category", style="magenta")
        table.add_column("Vol 24h", justify="right")
        table.add_column("Liquidity", justify="right")
        table.add_column("Bid/Ask", justify="right")
        table.add_column("Expiry", justify="right")

        for m in markets:
            expiry = m.end_date.strftime("%Y-%m-%d") if m.end_date else "—"
            table.add_row(
                m.question[:60],
                m.category,
                f"${m.volume_24h:,.0f}",
                f"${m.liquidity:,.0f}",
                f"{m.best_bid:.3f}/{m.best_ask:.3f}",
                expiry,
            )
        console.print(table)

    asyncio.run(_run())


@cli.command("paper-trade")
@click.option("--once", is_flag=True, help="Run a single scan cycle and exit")
@click.pass_context
def paper_trade(ctx: click.Context, once: bool) -> None:
    """Run the paper trading loop."""
    settings = ctx.obj["settings"]
    settings.trading_mode = TradingMode.PAPER

    async def _run() -> None:
        orch = Orchestrator(settings)
        if once:
            run = await orch.run_once()
            console.print(
                f"[bold]Run complete[/bold] id={run.run_id} "
                f"status={run.status.value} "
                f"markets={run.markets_scanned} "
                f"executed={run.trades_executed} "
                f"pnl=${run.realized_pnl:.2f}"
            )
        else:
            await orch.run_continuous()

    asyncio.run(_run())


@cli.command()
@click.option("--limit", default=10, show_default=True)
@click.pass_context
def runs(ctx: click.Context, limit: int) -> None:
    """Show recent run history."""
    settings = ctx.obj["settings"]

    async def _run() -> None:
        store = TradeStore(settings.database_url)
        await store.init()
        rows = await store.get_runs(limit=limit)

        table = Table(title=f"Last {limit} Runs")
        table.add_column("Run ID", style="dim", max_width=12)
        table.add_column("Mode")
        table.add_column("Status")
        table.add_column("Markets", justify="right")
        table.add_column("Executed", justify="right")
        table.add_column("PnL", justify="right")
        table.add_column("Started")

        for r in rows:
            pnl = r["realized_pnl"]
            pnl_str = f"[green]${pnl:.2f}[/green]" if pnl >= 0 else f"[red]-${abs(pnl):.2f}[/red]"
            table.add_row(
                r["run_id"][:8],
                r["trading_mode"],
                r["status"],
                str(r["markets_scanned"]),
                str(r["trades_executed"]),
                pnl_str,
                str(r["started_at"])[:16],
            )
        console.print(table)

    asyncio.run(_run())


@cli.command()
@click.argument("run_id")
@click.pass_context
def report(ctx: click.Context, run_id: str) -> None:
    """Show fills for a specific run."""
    settings = ctx.obj["settings"]

    async def _run() -> None:
        store = TradeStore(settings.database_url)
        await store.init()
        fills = await store.get_fills_for_run(run_id)

        if not fills:
            console.print(f"No fills found for run {run_id}")
            return

        table = Table(title=f"Fills for run {run_id[:8]}")
        table.add_column("Condition", max_width=16)
        table.add_column("Outcome")
        table.add_column("Side")
        table.add_column("Size", justify="right")
        table.add_column("Price", justify="right")
        table.add_column("Filled At")

        for f in fills:
            table.add_row(
                f["condition_id"][:16],
                f["outcome"],
                f["side"],
                f"${f['filled_size_usdc']:.2f}",
                f"{f['fill_price']:.4f}",
                str(f["filled_at"])[:16],
            )
        console.print(table)

    asyncio.run(_run())


@cli.command()
@click.pass_context
def positions(ctx: click.Context) -> None:
    """Show current portfolio positions."""
    settings = ctx.obj["settings"]

    async def _run() -> None:
        from .broker.paper import PaperBroker
        broker = PaperBroker(
            initial_cash=settings.paper_initial_cash,
            fill_slippage_bps=settings.paper_fill_slippage_bps,
        )
        portfolio = await broker.get_portfolio()

        console.print(f"[bold]Cash:[/bold] ${portfolio.cash_usdc:,.2f}")
        console.print(f"[bold]Realized PnL:[/bold] ${portfolio.realized_pnl:,.2f}")
        console.print(f"[bold]Open Positions:[/bold] {portfolio.open_position_count()}")

        if portfolio.positions:
            table = Table(title="Open Positions")
            table.add_column("Token ID", max_width=20)
            table.add_column("Outcome")
            table.add_column("Size", justify="right")
            table.add_column("Avg Entry", justify="right")
            table.add_column("Cost Basis", justify="right")

            for token_id, pos in portfolio.positions.items():
                table.add_row(
                    token_id[:20],
                    pos.outcome,
                    f"{pos.size_tokens:.4f}",
                    f"{pos.avg_entry_price:.4f}",
                    f"${pos.cost_basis_usdc:.2f}",
                )
            console.print(table)

    asyncio.run(_run())


@cli.command("risk-status")
@click.pass_context
def risk_status(ctx: click.Context) -> None:
    """Show risk engine configuration and limits."""
    s = ctx.obj["settings"]
    table = Table(title="Risk Limits")
    table.add_column("Parameter")
    table.add_column("Value", justify="right")

    table.add_row("Max notional/market", f"${s.risk_max_notional_per_market:.2f}")
    table.add_row("Max portfolio exposure", f"${s.risk_max_portfolio_exposure:.2f}")
    table.add_row("Max category exposure", f"${s.risk_max_category_exposure:.2f}")
    table.add_row("Max daily loss", f"${s.risk_max_daily_loss:.2f}")
    table.add_row("Max open positions", str(s.risk_max_open_positions))
    table.add_row("Max open orders", str(s.risk_max_open_orders))
    table.add_row("Signal staleness", f"{s.risk_signal_staleness_seconds}s")
    table.add_row("No-trade before expiry", f"{s.risk_expiry_no_trade_hours}h")
    table.add_row("Cooldown after N losses", str(s.risk_cooldown_after_losses))
    table.add_row("Cooldown duration", f"{s.risk_cooldown_duration_seconds}s")
    console.print(table)


@cli.command("sandbox-status")
@click.pass_context
def sandbox_status(ctx: click.Context) -> None:
    """Show Daytona sandbox status (Milestone 3 — requires DAYTONA_API_KEY)."""
    import os
    daytona_key = os.environ.get("DAYTONA_API_KEY")
    if not daytona_key:
        console.print(
            "[yellow]Daytona not configured.[/yellow] "
            "Set DAYTONA_API_KEY to enable sandbox orchestration (Milestone 3)."
        )
        return

    try:
        from daytona_sdk import Daytona  # type: ignore[import]
        client = Daytona(api_key=daytona_key)
        sandboxes = client.list()
        table = Table(title="Daytona Sandboxes")
        table.add_column("ID", style="dim")
        table.add_column("State")
        table.add_column("Created")
        for sb in sandboxes:
            table.add_row(
                str(sb.id)[:16],
                str(sb.state),
                str(getattr(sb, "created_at", "—")),
            )
        console.print(table)
    except ImportError:
        console.print(
            "[red]daytona-sdk not installed.[/red] "
            "Run: pip install daytona-sdk"
        )
    except Exception as e:
        console.print(f"[red]Daytona API error:[/red] {e}")
