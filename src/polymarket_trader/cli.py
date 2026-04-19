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
from .runtime import DaytonaRuntime, DaytonaRuntimeError

console = Console()


def _setup_logging(log_level: str, log_file: str) -> None:
    logger.remove()
    logger.add(sys.stderr, level=log_level, format="{time} {level} {message}")
    Path(log_file).parent.mkdir(parents=True, exist_ok=True)
    logger.add(log_file, level="DEBUG", rotation="50 MB", retention="30 days")


def _print_daytona_command_result(exit_code: int, sandbox_name: str, sandbox_id: str, output: str) -> None:
    console.print(
        f"[bold]Sandbox[/bold] {sandbox_name} "
        f"({sandbox_id[:12]}) exit_code={exit_code}"
    )
    if output.strip():
        console.out(output, end="" if output.endswith("\n") else "\n")


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
@click.option("--run-id", default=None, help="Specific run ID (defaults to most recent run)")
@click.pass_context
def positions(ctx: click.Context, run_id: str | None) -> None:
    """Show portfolio positions from a run (defaults to most recent)."""
    settings = ctx.obj["settings"]

    async def _run() -> None:
        store = TradeStore(settings.database_url)
        await store.init()

        if run_id is None:
            runs = await store.get_runs(limit=1)
            if not runs:
                console.print("[yellow]No runs found in the database.[/yellow]")
                return
            resolved_run_id = runs[0]["run_id"]
        else:
            resolved_run_id = run_id

        pnl_history = await store.get_pnl_history(resolved_run_id)
        if pnl_history:
            latest = pnl_history[-1]
            console.print(f"[bold]Run:[/bold] {resolved_run_id[:8]}")
            console.print(f"[bold]Cash:[/bold] ${latest['cash_usdc']:,.2f}")
            console.print(f"[bold]Realized PnL:[/bold] ${latest['realized_pnl']:,.2f}")
            console.print(f"[bold]Daily Loss:[/bold] ${latest['daily_loss']:,.2f}")
            console.print(f"[bold]Open Positions:[/bold] {latest['open_position_count']}")

        positions_data = await store.get_positions_for_run(resolved_run_id)
        if positions_data:
            table = Table(title=f"Positions — run {resolved_run_id[:8]}")
            table.add_column("Condition", max_width=16)
            table.add_column("Outcome")
            table.add_column("Category")
            table.add_column("Size", justify="right")
            table.add_column("Avg Entry", justify="right")
            table.add_column("Cost Basis", justify="right")
            table.add_column("Realized PnL", justify="right")

            for p in positions_data:
                pnl = p["realized_pnl"]
                pnl_str = (
                    f"[green]${pnl:.2f}[/green]"
                    if pnl >= 0
                    else f"[red]-${abs(pnl):.2f}[/red]"
                )
                table.add_row(
                    p["condition_id"][:16],
                    p["outcome"],
                    p["category"],
                    f"{p['size_tokens']:.4f}",
                    f"{p['avg_entry_price']:.4f}",
                    f"${p['cost_basis_usdc']:.2f}",
                    pnl_str,
                )
            console.print(table)
        else:
            console.print(f"No open positions in run {resolved_run_id[:8]}.")

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
@click.option("--role", default=None, help="Optional sandbox role label filter")
@click.option("--limit", default=20, show_default=True, help="Maximum sandboxes to show")
@click.pass_context
def sandbox_status(ctx: click.Context, role: str | None, limit: int) -> None:
    """Show Daytona sandbox status for this project."""
    settings = ctx.obj["settings"]
    try:
        runtime = DaytonaRuntime(settings)
        sandboxes = runtime.list_sandboxes(role=role, limit=limit)
        if not sandboxes:
            console.print("[yellow]No Daytona sandboxes found for this project.[/yellow]")
            return

        table = Table(title="Daytona Sandboxes")
        table.add_column("Name")
        table.add_column("ID", style="dim")
        table.add_column("Role")
        table.add_column("State")
        table.add_column("Auto Stop", justify="right")
        table.add_column("Created")
        for sb in sandboxes:
            if sb.auto_stop_interval is None:
                auto_stop = "—"
            elif sb.auto_stop_interval == 0:
                auto_stop = "off"
            else:
                auto_stop = f"{sb.auto_stop_interval}m"
            table.add_row(
                sb.name or "—",
                sb.sandbox_id[:16],
                sb.role or "—",
                sb.state,
                auto_stop,
                sb.created_at,
            )
        console.print(table)
    except DaytonaRuntimeError as e:
        console.print(f"[red]Daytona runtime error:[/red] {e}")
    except Exception as e:
        console.print(f"[red]Daytona API error:[/red] {e}")


@cli.command("sandbox-scan")
@click.option("--top", default=10, show_default=True, help="Number of markets to scan")
@click.option("--role", default="scanner", show_default=True, help="Daytona sandbox role label")
@click.option("--reuse/--fresh", default=True, show_default=True, help="Reuse an existing sandbox when available")
@click.pass_context
def sandbox_scan(ctx: click.Context, top: int, role: str, reuse: bool) -> None:
    """Run `scan` inside a Daytona sandbox."""
    settings = ctx.obj["settings"]
    try:
        runtime = DaytonaRuntime(settings)
        result = runtime.run_cli(
            ["scan", "--top", str(top)],
            role=role,
            reuse=reuse,
        )
        _print_daytona_command_result(
            result.exit_code,
            result.sandbox_name,
            result.sandbox_id,
            result.output,
        )
        if result.exit_code != 0:
            raise click.ClickException("Remote scan failed")
    except DaytonaRuntimeError as e:
        raise click.ClickException(str(e)) from e


@cli.command("sandbox-paper-trade-once")
@click.option("--role", default="trader", show_default=True, help="Daytona sandbox role label")
@click.option("--reuse/--fresh", default=True, show_default=True, help="Reuse an existing sandbox when available")
@click.pass_context
def sandbox_paper_trade_once(ctx: click.Context, role: str, reuse: bool) -> None:
    """Run a single paper trading cycle inside a Daytona sandbox."""
    settings = ctx.obj["settings"]
    settings.trading_mode = TradingMode.PAPER
    try:
        runtime = DaytonaRuntime(settings)
        result = runtime.run_cli(
            ["--mode", "paper", "paper-trade", "--once"],
            role=role,
            reuse=reuse,
        )
        _print_daytona_command_result(
            result.exit_code,
            result.sandbox_name,
            result.sandbox_id,
            result.output,
        )
        if result.exit_code != 0:
            raise click.ClickException("Remote paper trade failed")
    except DaytonaRuntimeError as e:
        raise click.ClickException(str(e)) from e


@cli.command()
@click.option("--days", default=30, show_default=True, help="How many days back to look for resolved markets")
@click.option("--cash", default=10_000.0, show_default=True, help="Starting cash in USDC")
@click.option("--min-volume", default=5_000.0, show_default=True, help="Minimum market volume/liquidity")
@click.option("--limit", default=50, show_default=True, help="Max number of resolved markets to evaluate")
@click.option("--no-cache", is_flag=True, help="Always re-fetch evidence, ignore DB cache")
@click.pass_context
def backtest(
    ctx: click.Context,
    days: int,
    cash: float,
    min_volume: float,
    limit: int,
    no_cache: bool,
) -> None:
    """Run strategy pipeline against recently resolved markets and measure hypothetical PnL."""
    settings = ctx.obj["settings"]
    settings.trading_mode = TradingMode.PAPER

    async def _run() -> None:
        from .backtest.runner import BacktestRunner
        from rich.table import Table

        runner = BacktestRunner(settings)
        summary = await runner.run(
            days_back=days,
            initial_cash=cash,
            min_volume=min_volume,
            market_limit=limit,
            use_evidence_cache=not no_cache,
        )

        console.print()
        console.rule("[bold]Backtest Summary[/bold]")

        stat_table = Table(show_header=False, box=None, padding=(0, 2))
        stat_table.add_column("Metric", style="bold")
        stat_table.add_column("Value", justify="right")

        win_color = "green" if summary.winning_trades >= summary.losing_trades else "red"
        pnl_color = "green" if summary.total_pnl >= 0 else "red"
        roi_color = "green" if summary.roi_pct >= 0 else "red"

        stat_table.add_row("Markets evaluated", str(summary.total_markets_evaluated))
        stat_table.add_row("Trades taken", str(summary.total_trades))
        stat_table.add_row(
            "Win / Loss",
            f"[{win_color}]{summary.winning_trades} / {summary.losing_trades}[/{win_color}]",
        )
        stat_table.add_row(
            "Win rate",
            f"[{win_color}]{summary.win_rate * 100:.1f}%[/{win_color}]",
        )
        stat_table.add_row(
            "Total PnL",
            f"[{pnl_color}]${summary.total_pnl:+.2f}[/{pnl_color}]",
        )
        stat_table.add_row(
            "ROI",
            f"[{roi_color}]{summary.roi_pct:+.2f}%[/{roi_color}]",
        )
        stat_table.add_row("Total invested", f"${summary.total_invested:.2f}")
        stat_table.add_row("Initial cash", f"${summary.initial_cash:,.2f}")
        stat_table.add_row("Final cash", f"${summary.final_cash:,.2f}")
        stat_table.add_row("Avg edge at entry", f"{summary.avg_edge_bps:.0f} bps")
        stat_table.add_row("Avg confidence", f"{summary.avg_confidence * 100:.1f}%")
        stat_table.add_row("Sharpe ratio", f"{summary.sharpe_ratio:.2f}")
        stat_table.add_row("Max drawdown", f"${summary.max_drawdown:.2f}")
        stat_table.add_row("Skipped (no edge)", str(summary.skipped_no_edge))
        stat_table.add_row("Skipped (no plan)", str(summary.skipped_no_plan))
        stat_table.add_row("Skipped (risk)", str(summary.skipped_risk))
        stat_table.add_row("Forecast failures", str(summary.forecast_failures))
        console.print(stat_table)

        if summary.trades:
            console.print()
            trade_table = Table(title="Per-Trade Results", show_lines=False)
            trade_table.add_column("Question", max_width=50, style="cyan")
            trade_table.add_column("Traded", justify="center")
            trade_table.add_column("Won", justify="center")
            trade_table.add_column("Entry", justify="right")
            trade_table.add_column("Size", justify="right")
            trade_table.add_column("PnL", justify="right")
            trade_table.add_column("Edge", justify="right")

            for t in sorted(summary.trades, key=lambda x: x.pnl, reverse=True):
                won_str = "[green]YES[/green]" if t.won else "[red]NO[/red]"
                pnl_str = (
                    f"[green]${t.pnl:+.2f}[/green]"
                    if t.pnl >= 0
                    else f"[red]${t.pnl:+.2f}[/red]"
                )
                trade_table.add_row(
                    t.question[:50],
                    t.outcome_traded,
                    won_str,
                    f"{t.entry_price:.3f}",
                    f"${t.size_usdc:.2f}",
                    pnl_str,
                    f"{t.edge_bps:.0f}bps",
                )
            console.print(trade_table)

    asyncio.run(_run())


@cli.command("live-trade")
@click.option("--once", is_flag=True, help="Run a single cycle and exit")
@click.pass_context
def live_trade(ctx: click.Context, once: bool) -> None:
    """Run the live trading loop. Geoblock + balance checks run before every cycle."""
    settings = ctx.obj["settings"]
    settings.trading_mode = TradingMode.LIVE

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
@click.argument("run_id")
@click.pass_context
def reconcile(ctx: click.Context, run_id: str) -> None:
    """Compare fills vs persisted positions for a run and surface any drift."""
    settings = ctx.obj["settings"]

    async def _run() -> None:
        store = TradeStore(settings.database_url)
        await store.init()
        discrepancies = await store.reconcile_positions(run_id)

        if not discrepancies:
            console.print(
                f"[green]No position drift found for run {run_id[:8]}[/green]"
            )
            return

        table = Table(title=f"Position Drift — run {run_id[:8]}")
        table.add_column("Condition", max_width=16)
        table.add_column("Net Fills", justify="right")
        table.add_column("Position Cost", justify="right")
        table.add_column("Drift", justify="right", style="red")

        for d in discrepancies:
            table.add_row(
                d["condition_id"][:16],
                f"${d['net_fills_usdc']:.4f}",
                f"${d['position_cost_basis_usdc']:.4f}",
                f"${d['drift_usdc']:.4f}",
            )
        console.print(table)

    asyncio.run(_run())


if __name__ == "__main__":
    cli()
