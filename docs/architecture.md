# System Architecture

## Overview

The system is a multi-layer autonomous trading pipeline. Each layer has a single responsibility and communicates through typed domain models. No layer reaches across its boundary.

```
┌─────────────────────────────────────────────────────────────────┐
│                        CLI / Operator                           │
│          scan │ paper-trade │ report │ positions │ runs         │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                       Orchestrator                              │
│   Coordinates the scan → research → forecast → risk → execute  │
│   loop. Manages concurrency, error counts, and run records.     │
└──┬──────────┬──────────┬──────────┬──────────┬─────────────────┘
   │          │          │          │          │
   ▼          ▼          ▼          ▼          ▼
Discovery  Research  Intelligence  Strategy   Broker
Scanner    Pipeline  Forecaster   Scorer     PaperBroker
           Evidence  Ranker       Planner    PolymarketBroker
                                 Risk Engine
   │          │          │          │          │
   └──────────┴──────────┴──────────┴──────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                      Connectors                                 │
│   GammaClient │ ClobClient │ SearXNGClient │ LightpandaClient   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                  External Services                              │
│  Polymarket Gamma API │ CLOB API │ SearXNG │ Lightpanda         │
│  Ollama / OpenAI-compatible LLM endpoint                       │
└─────────────────────────────────────────────────────────────────┘
                            │
┌───────────────────────────▼─────────────────────────────────────┐
│                     Persistence                                 │
│   TradeStore (SQLAlchemy + aiosqlite / asyncpg)                │
│   Tables: runs │ market_snapshots │ evidence │ forecasts        │
│           orders │ fills                                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## Layer Descriptions

### 1. Discovery Layer (`discovery/scanner.py`)

**Input:** Settings (scan parameters)
**Output:** `list[MarketSnapshot]`

1. Calls `GammaClient.fetch_active_markets()` — filtered by volume and liquidity
2. Passes raw market list to `Ranker` — LLM ranks by researchability
3. Enriches top-N markets via `ClobClient.enrich_market()` — adds bid/ask/spread/tick_size
4. Returns fully enriched `MarketSnapshot` objects

Concurrency: CLOB enrichment runs with `asyncio.Semaphore(5)` to avoid rate limits.

---

### 2. Research Layer (`research/pipeline.py`)

**Input:** `MarketSnapshot`
**Output:** `list[EvidenceItem]`

1. Calls the configured LLM provider to generate 3 targeted search queries
2. Runs all queries in parallel against `SearXNGClient`
3. Deduplicates results by URL and snippet hash (MD5)
4. Optionally enriches top results with `LightpandaClient.fetch_text()` for full page text
5. Filters to items published within 168 hours

Concurrency: Search queries run in parallel. Browser enrichment runs in parallel per item.

---

### 3. Intelligence Layer (`intelligence/`)

#### Ranker (`ranker.py`)

**Input:** `list[MarketSnapshot]` (up to 50)
**Output:** `list[MarketSnapshot]` ranked by researchability

Calls the LLM to rank markets. Falls back to volume sort on failure.

#### Forecaster (`forecaster.py`)

**Input:** `MarketSnapshot` + `list[EvidenceItem]`
**Output:** `Forecast | None`

1. Formats evidence as numbered source list
2. Calls `complete_json()` with Pydantic schema `_ForecastOut`
3. Validates that probabilities sum > 0 (normalises to 1.0)
4. Maps LLM outcomes to token IDs by case-insensitive name matching
5. Returns `Forecast` with `confidence`, `rationale`, `outcomes`, `sources_used`

Rejects malformed LLM output via Pydantic validation — returns `None` on failure.

---

### 4. Strategy Layer (`strategy/`)

#### OpportunityScorer (`scorer.py`)

**Input:** `MarketSnapshot` + `Forecast`
**Output:** `OpportunityScore | None`

Computes edge in basis points: `(fair_probability - market_price) × 10,000`

Returns `None` if `abs(edge_bps) < min_edge_bps` (default 200 bps).

Score formula:
```
final_score = (edge_bps / 10_000) × confidence × liquidity_factor × expiry_factor
```
- `liquidity_factor = min(liquidity / 10_000, 1.0)`
- `expiry_factor = 0.0` if < 2h, linear ramp from 0→1 over 0–24h, then 1.0

#### ExecutionPlanner (`planner.py`)

**Input:** `OpportunityScore` + `MarketSnapshot` + `portfolio_cash`
**Output:** `ExecutionPlan | None`

1. Determines side: BUY if edge > 0, SELL if edge < 0
2. Sets limit price: `best_ask` for BUY, `best_bid` for SELL (falls back to token price)
3. Computes Kelly fraction (conservative: `kelly × confidence × 0.25`, capped at 5% of cash)
4. Caps size at `risk_max_notional_per_market`
5. Snaps limit price to tick size
6. Returns `None` if size < `min_order_size`

Slippage for estimated fill: live uses `LIVE_FILL_SLIPPAGE_BPS`, paper uses `PAPER_FILL_SLIPPAGE_BPS`.

---

### 5. Risk Layer (`risk/engine.py`)

**Input:** `ExecutionPlan` + `MarketSnapshot` + `PortfolioState` + open_order_count
**Output:** `RiskDecision`

Evaluated in this exact order (first rejection wins):

| Check | Parameter |
|-------|-----------|
| Global cooldown | Automatic after 2× `RISK_COOLDOWN_AFTER_LOSSES` global losses |
| Market cooldown | Automatic after `RISK_COOLDOWN_AFTER_LOSSES` losses on same market |
| Signal staleness | `RISK_SIGNAL_STALENESS_SECONDS` |
| Expiry proximity | `RISK_EXPIRY_NO_TRADE_HOURS` |
| Notional limit | `RISK_MAX_NOTIONAL_PER_MARKET` |
| Portfolio exposure | `RISK_MAX_PORTFOLIO_EXPOSURE` |
| Category exposure | `RISK_MAX_CATEGORY_EXPOSURE` (per `market.category`) |
| Daily loss | `RISK_MAX_DAILY_LOSS` |
| Open positions | `RISK_MAX_OPEN_POSITIONS` |
| Open orders | `RISK_MAX_OPEN_ORDERS` |

Cooldown tracking: per-market streak + global streak. Win resets market streak and decrements global counter.

---

### 6. Broker Layer (`broker/`)

#### BaseBroker (`base.py`)

Abstract interface:
```python
submit(plan, run_id) -> OrderRecord
get_portfolio()      -> PortfolioState
open_order_count()   -> int
```

#### PaperBroker (`paper.py`)

In-memory simulation. No external calls.

- BUY: deducts cash, opens/updates `PositionState`, creates `FillRecord` + `OrderRecord`
- SELL: closes position proportionally, realises PnL, accumulates `daily_loss`
- Insufficient cash → `OrderStatus.REJECTED`
- Average-price tracking on subsequent buys to same token

#### PolymarketBroker (`polymarket.py`)

Live broker backed by `py-clob-client`.

Pre-flight required before first order (all three must pass):
1. `ClobClient.check_geoblock()` — hard fail if blocked, switches to paper-only
2. Derive API credentials from private key (EIP-712 signature)
3. Balance + allowance check — hard fail if USDC balance or CTF Exchange allowance < `RISK_MAX_NOTIONAL_PER_MARKET`

Order flow: `create_order(OrderArgs)` → `post_order(signed, order_type)` → parse response status.

Supports `FOK` and `FAK` order types. Persists raw exchange response in `OrderRecord.raw_response`.

---

### 7. Persistence Layer (`persistence/store.py`)

`TradeStore` wraps SQLAlchemy async session. Tables:

| Table | Purpose | Written by |
|-------|---------|-----------|
| `runs` | One row per `run_once()` call | `save_run()` / `update_run()` |
| `market_snapshots` | Every market scanned per run | `save_market_snapshot()` |
| `evidence` | Evidence items per market per run | `save_evidence()` |
| `forecasts` | LLM forecast per market per run | `save_forecast()` |
| `execution_plans` | Every non-None plan produced | `save_execution_plan()` |
| `risk_events` | Every risk decision (approved + rejected) | `save_risk_event()` |
| `orders` | Every order submitted (paper or live) | `save_order()` |
| `fills` | Every fill produced | `save_fill()` |
| `positions` | Position snapshot at run end | `save_position_snapshot()` |
| `pnl_snapshots` | Portfolio cash/PnL snapshot at run end | `save_pnl_snapshot()` |
| `errors` | Exceptions from orchestrator + per-market | `save_error()` |

Notable methods:
- `get_cached_evidence(condition_id, max_age_hours=6.0)` — returns evidence from previous runs within the freshness window; orchestrator checks this before calling the full research pipeline
- `reconcile_positions(run_id)` — compares fill net flows against position cost basis and returns drift records

Database URL configurable: `sqlite+aiosqlite:///./polymarket_trader.db` (local dev) or `postgresql+asyncpg://...` (production).

---

## Data Flow — Single Scan Cycle

```
Orchestrator.run_once()
  │
  ├─ [LIVE only] PolymarketBroker.preflight()
  │    ├─ ClobClient.check_geoblock()           → hard fail if blocked
  │    ├─ derive API credentials (EIP-712)
  │    └─ get_balance_allowance()               → hard fail if insufficient
  │
  ├─ MarketScanner.scan(top_n=SCAN_MARKET_LIMIT)
  │    ├─ GammaClient.fetch_active_markets()    → list[raw market]
  │    ├─ Ranker.rank()                         → list[MarketSnapshot] (LLM-ranked)
  │    └─ ClobClient.enrich_market() ×N         → list[MarketSnapshot] + bid/ask
  │
  ├─ TradeStore.save_market_snapshot() ×N
  │
  ├─ For each market (concurrency=3):
  │    ├─ TradeStore.get_cached_evidence()      → hit: skip pipeline, use cached items
  │    │                                           miss: run full pipeline below
  │    ├─ ResearchPipeline.research()           [cache miss only]
  │    │    ├─ LLM provider: generate 3 queries
  │    │    ├─ SearXNG: parallel search ×3
  │    │    ├─ Lightpanda: enrich top results (optional)
  │    │    └─ Deduplicate (URL + MD5 snippet) + freshness filter (168h)
  │    │
  │    ├─ TradeStore.save_evidence()            [cache miss only]
  │    │
  │    ├─ Forecaster.forecast()
  │    │    └─ LLM provider: complete_json(_ForecastOut)
  │    │
  │    ├─ TradeStore.save_forecast()
  │    │
  │    └─ OpportunityScorer.score()             → OpportunityScore | None
  │
  ├─ Sort scores by final_score DESC
  │
  ├─ For each scored opportunity:
  │    ├─ ExecutionPlanner.plan()               → ExecutionPlan | None
  │    ├─ TradeStore.save_execution_plan()
  │    ├─ RiskEngine.evaluate()                 → RiskDecision
  │    ├─ TradeStore.save_risk_event()
  │    ├─ if APPROVED:
  │    │    ├─ broker.submit()                  → OrderRecord
  │    │    ├─ TradeStore.save_order()
  │    │    ├─ [FILLED] RiskEngine.record_win()
  │    │    └─ [FILLED] TradeStore.save_fill()
  │    └─ if REJECTED/EXPIRED: RiskEngine.record_loss()
  │
  ├─ TradeStore.save_pnl_snapshot()             (cash, realized PnL, daily loss)
  ├─ TradeStore.save_position_snapshot()        [paper mode only]
  └─ TradeStore.update_run()                    (final stats + status)
```

---

## Concurrency Model

- Market enrichment: `asyncio.Semaphore(5)` — 5 parallel CLOB calls
- Market processing: `asyncio.Semaphore(3)` — 3 markets researched + forecasted simultaneously
- Search queries: fully parallel per market
- Browser enrichment: fully parallel per evidence item

All async, no threads. Single event loop per process.

---

## Provider Abstraction

All LLM calls go through `OpenAICompatibleProvider`. The OpenAI SDK is used against a configurable OpenAI-compatible base URL. This means:

- Any OpenAI-compatible model can be selected via `LLM_MODEL`
- Per-task model overrides: `LLM_MODEL_RANKING`, `LLM_MODEL_FORECASTING`, `LLM_MODEL_EXTRACTION`
- `complete()` — free-form text response
- `complete_json(schema)` — Pydantic-validated structured response; injects schema into system prompt

---

## Deployment Topology (Milestone 3+)

```
Control Server
├── Scheduler (runs scan cycle every SCAN_INTERVAL_SECONDS)
├── PostgreSQL (persistent state)
├── Redis (optional: job queue, cache)
├── SearXNG (self-hosted search)
└── Daytona SDK client
      │
      └─ Daytona Sandboxes
           ├── Worker: market-scan
           ├── Worker: research
           ├── Worker: forecast
           └── Worker: execution (paper or live)
```

Milestone 1–2 run everything in-process. Milestone 3 splits control plane from workers.
