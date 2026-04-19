# Autonomous Polymarket Trader PRD

## Document Status

- Status: Updated v2
- Date: 2026-04-20
- Scope: End-to-end product and technical requirements for turning the current prototype into a continuously running autonomous trading system

### Implementation Status Summary (as of 2026-04-20)

| Milestone | Status | Notes |
|-----------|--------|-------|
| M1 — Paper Trader Foundation | ✅ Complete | All deliverables shipped and tested |
| M2 — Research Stack Upgrade | ✅ Complete | SearXNG + Lightpanda + evidence cache |
| M3 — Continuous Runtime | 🔶 Partial | Daytona done; health checks + alerting missing |
| M4 — Live Trading Readiness | 🔶 Partial | Live broker + reconciliation done; kill switch + alerting missing |

## 1. Overview

This project will evolve the current Polymarket agent prototype into a production-oriented autonomous trading platform with:

- paper trading first, live trading later
- structured research and decision pipelines
- self-hosted web search using SearXNG
- headless web browsing using Lightpanda
- model access through local OpenAI-compatible backends, with Ollama as the default
- isolated agent execution inside Daytona sandboxes
- optional 24/7 server orchestration and monitoring

The current repo already contains a basic autonomous path in `scripts/python/cli.py` and `agents/application/trade.py`, but it is not safe or complete enough for unattended operation. It lacks a risk engine, persistent state, proper execution guards, reconciliation, and meaningful tests.

## 2. Problem

The original prototype (`agents/` directory, preserved for reference) had these limitations — all resolved in the current `src/polymarket_trader/` implementation:

| Original Problem | Resolution |
|-----------------|------------|
| `ChatOpenAI` hard-wired | Provider abstraction (`OpenAICompatibleProvider`); Ollama default |
| OpenAI embeddings hard-wired | Embeddings removed from trading path entirely |
| Tavily proof-of-concept search | `SearXNGClient` with JSON output, retry, dedup |
| Generic prompt filtering | Typed `Forecast` + `OpportunityScore` with edge_bps formula |
| Unbounded recursion on exception | `tenacity` bounded retry; no recursion in orchestrator |
| No paper broker or portfolio state | `PaperBroker` with positions, cash, PnL, daily loss |
| No persistent state | SQLAlchemy async ORM, 12 tables, all artifacts stored |
| No 24/7 runtime | `run_continuous()` loop + Daytona sandbox workers |
| Tests are placeholders | 39 real tests covering risk, broker, strategy, models, persistence |

Remaining gaps (still open):
- No Prometheus / Grafana metrics integration
- No alerting channel (Slack / Telegram / Discord / email)
- No kill switch mechanism
- `resume-run` CLI command not implemented
- Control server not separated from in-process orchestrator

## 3. Product Goal

Build an autonomous research and trading agent for Polymarket that can:

- discover candidate markets
- gather supporting evidence from structured APIs and the web
- estimate fair probabilities
- compare fair value against executable market prices
- enforce hard risk controls
- simulate or execute trades
- run continuously with logs, metrics, alerts, and recoverability

## 4. Non-Goals For V1

- fully autonomous live trading in blocked jurisdictions
- high-frequency market making
- multi-exchange support
- advanced quantitative backtesting against years of historical data
- complex portfolio optimization across hundreds of simultaneously active positions
- mobile app or end-user GUI

## 5. Compliance And Operating Constraints

### 5.1 Hard requirement

The system must support two modes:

- `paper`
- `live`

Default mode must be `paper`.

### 5.2 Jurisdiction gate

The repo README states that Polymarket Terms of Service prohibit US persons and persons from certain other jurisdictions from trading through the UI or API. Current Polymarket documentation also provides a geoblock endpoint for pre-trade eligibility checks.

Requirements:

- the system must call the geoblock check before enabling any live order flow
- if blocked, the system must hard fail into paper-only mode
- no hidden bypass behavior is allowed in code or documentation
- paper mode must remain fully usable even when live mode is blocked

### 5.3 Safety policy

Before any live trade is placed, the system must pass:

- compliance checks
- configuration validation
- key presence validation
- balance and allowance validation
- risk engine approval
- execution venue sanity checks

## 6. Users

Primary users:

- builder/operator running the agent
- researcher tuning prompts, models, and search sources
- engineer maintaining runtime, infrastructure, and execution safety

Secondary users:

- reviewer auditing decisions and logs
- future collaborators adding strategies and connectors

## 7. Success Criteria

### 7.1 Functional

- the system can scan active Polymarket markets and rank opportunities
- the system can perform paper trading end-to-end
- the system can persist decisions, fills, PnL, and errors
- the system can recover from transient failures without manual intervention

### 7.2 Quality

- every trade idea is traceable to evidence and pricing inputs
- every execution decision is reproducible from stored artifacts
- the runtime can survive process restarts without losing state
- tests cover core pricing, sizing, risk, and execution guards

### 7.3 Operational

- paper trader can run unattended for 7+ days
- server and sandbox runtime can restart cleanly
- alerts fire on stuck loops, repeated failures, or risk breaches

## 8. Product Principles

- paper-first before live trading
- structured outputs over free-form parsing
- deterministic guards around non-deterministic model behavior
- self-host key external dependencies where it materially improves control
- isolate untrusted browsing and tool execution
- keep strategy logic separate from infrastructure logic

## 9. Proposed System

### 9.1 Core subsystems

1. Market Discovery
   - discover events and markets from Gamma API
   - enrich with CLOB market data and Data API account state

2. Research
   - SearXNG for broad web search
   - Lightpanda for page retrieval, rendering, and evidence extraction on JS-heavy sites
   - News and other structured connectors where useful

3. Intelligence Layer
   - local-first LLM access for ranking, summarization, forecasting, and extraction
   - structured JSON outputs only for machine-consumed decisions

4. Strategy Engine
   - candidate scoring
   - fair probability estimation
   - edge computation
   - risk checks
   - execution planning

5. Broker Layer
   - paper broker for simulation
   - live Polymarket broker for eligible environments only

6. Runtime
   - Daytona sandbox for isolated agent execution
   - server process for scheduling, orchestration, metrics, and persistence

7. Observability
   - logs
   - trade journal
   - run artifacts
   - metrics and alerts

## 10. Architecture Decisions

### 10.1 Replace direct OpenAI usage with local OpenAI-compatible providers

Current state:

- `agents/application/executor.py` uses `ChatOpenAI`
- `agents/connectors/chroma.py` uses `OpenAIEmbeddings`
- `.env.example` expects `OPENAI_API_KEY`

Target state:

- default local development to `ollama`
- keep `openrouter` and generic OpenAI-compatible endpoints as optional backends
- introduce a model provider abstraction so model backend is configurable
- preserve the option to use OpenAI-compatible SDK clients where practical

Requirements:

- add provider config fields:
  - `LLM_PROVIDER=ollama`
  - `OLLAMA_BASE_URL=http://localhost:11434/v1`
  - `OPENAI_COMPATIBLE_BASE_URL`
  - `OPENROUTER_API_KEY`
  - `LLM_MODEL`
- optionally retain `openrouter` as a non-local provider, not as the default
- support model overrides per task type:
  - ranking model
  - forecasting model
  - extraction model

Notes:

- Ollama and vLLM expose OpenAI-compatible APIs that can be used via base URL switching
- optional attribution headers may be configured, but must not be required for core execution

### 10.2 Replace ad hoc web search with self-hosted SearXNG

Current state:

- `agents/connectors/search.py` is a Tavily example script and is not integrated into the trading pipeline

Target state:

- self-host SearXNG as the default search backend
- build a first-class `SearchClient` abstraction
- use JSON search responses and source ranking

Requirements:

- deploy SearXNG as a self-hosted service
- enable JSON output in SearXNG config
- add environment variables:
  - `SEARCH_PROVIDER=searxng`
  - `SEARXNG_BASE_URL`
  - `SEARXNG_TIMEOUT_SECONDS`
- normalize search results into a consistent schema:
  - `title`
  - `url`
  - `snippet`
  - `source`
  - `published_at`
  - `score`

### 10.3 Add Lightpanda as headless browser worker

Purpose:

- fetch and render JavaScript-heavy pages
- resolve dynamic content not available through simple HTTP fetches
- capture page text, metadata, and optionally screenshots

Requirements:

- run Lightpanda as a separate browser service reachable from the agent runtime
- use CDP-compatible automation
- keep browser tasks separate from the trading loop so browsing failures do not freeze the core agent
- enforce domain allowlists, timeouts, max page size, and fetch limits

### 10.4 Use Daytona for isolated execution

Purpose:

- run research and strategy workloads inside isolated sandboxes
- reduce blast radius from browser automation, parsers, and third-party code
- support persistent runtime and controlled restart behavior

Requirements:

- create Daytona sandboxes programmatically
- configure `auto_stop_interval=0` for always-on sandboxes where justified
- support stop/start/archive flows
- persist long-lived state outside ephemeral process memory
- support remote execution from a control server

### 10.5 Split control plane from worker plane

Recommended topology:

- control server:
  - scheduler
  - API or CLI trigger layer
  - persistent database
  - metrics
  - alerting
  - sandbox lifecycle management
- worker sandboxes:
  - market scan jobs
  - search and browse jobs
  - forecast jobs
  - execution planning jobs
  - optional live execution jobs

This avoids binding core orchestration to a single process inside a single sandbox.

## 11. Functional Requirements

### 11.1 Market discovery

The system must:

- fetch active, non-archived, non-closed markets and events
- support pagination and rate limit handling
- normalize market and token metadata
- cache snapshots used for each decision cycle

### 11.2 Research pipeline

The system must:

- generate search queries per market candidate
- fetch search results from SearXNG
- browse selected result pages using Lightpanda when needed
- extract evidence into structured records
- deduplicate sources and avoid low-signal spam pages

### 11.3 Forecasting and scoring

The system must:

- estimate fair probabilities per outcome
- return structured JSON containing:
  - confidence
  - rationale summary
  - supporting sources
  - fair probability by outcome
  - timestamp
- reject malformed model outputs
- score opportunities based on edge after cost assumptions

### 11.4 Pricing and execution planning

The system must:

- query order book, best bid/ask, spread, and tick size
- estimate fill price and slippage
- determine executable side and size
- create an `ExecutionPlan` object before any broker action

### 11.5 Risk engine

The system must enforce:

- max notional per market
- max portfolio exposure
- max category exposure
- max daily loss
- max open positions
- max open orders
- stale signal rejection
- no-trade windows near expiry or resolution when configured
- cooldown after repeated losses or repeated execution errors

### 11.6 Broker layer

The system must support:

- `PaperBroker`
- `PolymarketBroker`

Paper broker requirements:

- simulate fills based on configured fill logic
- track positions, cash, realized PnL, and unrealized PnL
- log every order, fill, and cancellation

Live broker requirements:

- verify geoblock and mode gates
- verify balances and allowances
- validate token id, side, tick size, and order type
- support `FOK` and `FAK` intentionally
- persist exchange responses for reconciliation

### 11.7 State and reporting

The system must persist:

- run metadata
- market snapshots
- evidence records
- model outputs
- execution plans
- broker actions
- positions
- realized and unrealized PnL
- risk events
- errors

The system must expose:

- scan report
- paper trading report
- position report
- run history
- error report

## 12. Non-Functional Requirements

### 12.1 Reliability

- no unbounded recursion
- bounded retries with backoff
- idempotent job handling where possible
- graceful degradation when search or browsing is unavailable

### 12.2 Performance

- scan cycle should complete within configurable time budget
- research and forecasting tasks should be parallelizable
- repeated market scans should reuse cached evidence when still fresh

### 12.3 Security

- no secrets committed to repo
- separate keys by environment
- principle of least privilege for server and sandbox credentials
- isolate browser automation and external content parsing

### 12.4 Observability

- structured logs
- trace id per decision cycle
- metrics for runs, failures, fills, and latency
- alerts for repeated failures and risk-triggered shutdowns

## 13. Data Model

The refactor should introduce explicit typed models for:

- `MarketSnapshot`
- `EvidenceItem`
- `Forecast`
- `OpportunityScore`
- `TradeIdea`
- `ExecutionPlan`
- `OrderRecord`
- `FillRecord`
- `PositionState`
- `PortfolioState`
- `RiskDecision`
- `RunRecord`

These should replace free-form string parsing and tuple-heavy flows in the current implementation.

## 14. CLI And Operator UX

Implemented commands (all working as of 2026-04-20):

```bash
python -m polymarket_trader.cli scan                    # rank live markets
python -m polymarket_trader.cli paper-trade [--once]    # run paper loop
python -m polymarket_trader.cli live-trade  [--once]    # run live loop (gated)
python -m polymarket_trader.cli report <run_id>         # fills for a run
python -m polymarket_trader.cli positions [--run-id X]  # positions from DB
python -m polymarket_trader.cli runs [--limit N]        # run history
python -m polymarket_trader.cli risk-status             # show risk limits
python -m polymarket_trader.cli reconcile <run_id>      # fill vs position drift
python -m polymarket_trader.cli sandbox-status          # Daytona sandbox list
python -m polymarket_trader.cli sandbox-scan            # remote scan in sandbox
python -m polymarket_trader.cli sandbox-paper-trade-once  # remote paper trade
```

Not yet implemented:

- `resume-run` — resume an interrupted run from its last checkpoint (M4+)

## 15. Infrastructure Plan

### 15.1 Services

Minimum deployment:

- app server
- database
- SearXNG
- Lightpanda browser service
- Daytona-managed worker sandboxes

Recommended optional services:

- Redis for queueing and cache
- Prometheus-compatible metrics collector
- Grafana dashboard
- alerting channel integration

### 15.2 Deployment model

Phase 1:

- local development
- local paper trader
- optional local Docker compose for SearXNG and DB

Phase 2:

- single long-lived server as control plane
- Daytona sandboxes launched per worker role or per task type

Phase 3:

- 24/7 managed deployment with health checks, restart policies, and alerting

### 15.3 Runtime split

The control server should:

- run scheduler
- own database and queue
- manage Daytona sandboxes
- expose operator commands or API

Each sandbox should:

- run one isolated worker role
- receive a bounded task
- return structured artifacts

## 16. Milestones

### Milestone 1: Paper Trader Foundation — ✅ COMPLETE

Deliverables shipped:

- [x] Refactored orchestrator (`orchestrator.py`) with typed domain models
- [x] Provider abstraction (`providers/`) — Ollama default, OpenRouter + generic OpenAI-compat optional
- [x] `PaperBroker` — fills, slippage, average-price tracking, daily loss, cash checks
- [x] `TradeStore` — 12 tables: runs, snapshots, evidence, forecasts, plans, risk events, orders, fills, positions, PnL, errors
- [x] Risk engine v1 — all 10 rules, per-market + global cooldown
- [x] 39 real tests covering risk, broker, strategy, models, persistence
- [x] CLI: `scan`, `paper-trade`, `report`, `positions`, `runs`, `risk-status`
- [x] Orchestrator fully wires risk feedback (`record_win`/`record_loss`)
- [x] All persistence calls active (`save_execution_plan`, `save_risk_event`, `save_pnl_snapshot`, `save_position_snapshot`, `save_error`)

Exit criteria met:
- Full paper-trading loop runs end-to-end
- No live execution path reachable by default
- Test suite covers all critical decision logic

---

### Milestone 2: Research Stack Upgrade — ✅ COMPLETE

Deliverables shipped:

- [x] `SearXNGClient` — JSON search, 3-attempt retry, date parsing (3 formats)
- [x] `LightpandaClient` — CDP fetch with HTTP fallback, scheme allowlist, max page bytes
- [x] `ResearchPipeline` — parallel query generation, parallel search, browser enrichment, URL + MD5 snippet dedup, 168h freshness filter
- [x] Evidence caching — `get_cached_evidence()` with 6h window; orchestrator checks cache before re-running pipeline
- [x] Per-run evidence artifacts stored in DB

Exit criteria met:
- Agent gathers evidence from search + rendered pages
- Research artifacts stored per run
- Cache avoids redundant LLM + search calls within 6h window

---

### Milestone 3: Continuous Runtime — 🔶 PARTIAL

Deliverables shipped:

- [x] `DaytonaRuntime` — sandbox lifecycle, bootstrap, remote CLI execution
- [x] `run_continuous()` — asyncio sleep loop with configurable `SCAN_INTERVAL_SECONDS`
- [x] CLI: `sandbox-status`, `sandbox-scan`, `sandbox-paper-trade-once`
- [x] `runtime_env()` — passes settings to sandboxes, excludes secrets in paper mode

Still needed:

- [ ] Health check endpoint (HTTP ping or watchdog)
- [ ] Retry policy for stuck scan cycles (timeout + restart)
- [ ] Prometheus metrics (run count, fill count, latency, errors)
- [ ] Grafana dashboard config
- [ ] Server deployment docs (systemd / Docker / supervisor)
- [ ] 7-day unattended paper mode stability verification

Exit criteria not yet met: unattended 7-day run not confirmed.

---

### Milestone 4: Live Trading Readiness — 🔶 PARTIAL

Deliverables shipped:

- [x] `PolymarketBroker` — geoblock preflight, credential derivation, FOK/FAK/GTC, raw response persistence
- [x] Balance + allowance validation in `preflight()` — hard fails if below `risk_max_notional_per_market`
- [x] `reconcile` CLI command — fill vs position cost-basis drift detection
- [x] `live-trade` CLI command — forces LIVE mode, supports `--once`
- [x] Geoblock check gates all live order flow

Still needed:

- [ ] Kill switch mechanism (file flag or signal handler that halts trading immediately)
- [ ] Alerting integration (at minimum: email or Telegram on risk breach / stuck loop)
- [ ] `resume-run` command
- [ ] Live broker end-to-end test in eligible environment
- [ ] Balance / allowance approval helper script (approve CTF Exchange)

Exit criteria not yet met: kill switch and alerting missing.

## 17. Acceptance Criteria

The project is considered successful for the first production-grade release when:

- the paper trading system is stable and fully observable
- Ollama is the default model backend, with OpenRouter supported as an override
- SearXNG is the default web search backend
- Lightpanda is available for dynamic page retrieval
- Daytona is used for isolated worker execution
- the control server can manage continuous operation
- live trading remains guarded by compliance and risk checks

## 18. Risks

### 18.1 Product risks

- no real edge despite strong infrastructure
- overfitting prompts to recent events
- excessive reliance on low-quality web sources

### 18.2 Technical risks

- model output instability
- search quality variance across engines
- browser automation failures on anti-bot protected sites
- sandbox cost growth for always-on workers
- state drift between market snapshots and execution time

### 18.3 Compliance risks

- operator running live mode from blocked region
- code paths that accidentally bypass live-trading gates

## 19. Open Questions

| Question | Status |
|----------|--------|
| Which local models for ranking vs forecasting vs extraction? | Open — use `LLM_MODEL_RANKING/FORECASTING/EXTRACTION` overrides to tune per-task |
| Migrate embeddings off OpenAI? | Resolved — embeddings removed from trading path entirely; no embedding dependency remains |
| SearXNG + Lightpanda: same host or separate services? | Open — docker-compose puts them on same host; separate for production recommended |
| One long-lived sandbox or short-lived task sandboxes? | Open — current code supports both; decision deferred to M3 ops work |
| SQLite local + Postgres server, or Postgres everywhere? | Resolved — SQLite for dev (`DATABASE_URL` default), asyncpg for Postgres in production; same ORM code |
| Alerting channel? | Open — required for M4 exit; Telegram recommended for simplicity |
| How to approve USDC allowance for live trading? | Open — need helper script to call CTF Exchange `approve()` via web3 |

## 20. Remaining Work (as of 2026-04-20)

Steps 1–7 are complete. Remaining:

8. **Health checks + watchdog** — HTTP ping endpoint or file-based heartbeat; restart policy for stuck cycles
9. **Prometheus metrics** — instrument `run_once()` with counters: runs, fills, errors, latency; expose `/metrics`
10. **Grafana dashboard** — standard trading dashboard: PnL over time, fill rate, error rate, risk rejections
11. **Alerting** — Telegram bot (or email) firing on: stuck loop, N consecutive errors, risk breach, daily loss limit hit
12. **Kill switch** — `SIGTERM` handler + `kill_switch.flag` file check at top of each cycle
13. **`resume-run` command** — load last incomplete `RunRecord` and continue from scored markets
14. **Live environment test** — end-to-end live order test in eligible jurisdiction with small notional
15. **USDC allowance helper** — script to approve CTF Exchange contract once per wallet
16. **7-day paper stability run** — confirm unattended operation, check for memory leaks and DB growth

## 21. External References

These informed the architecture as of 2026-04-19:

- Polymarket API introduction: `https://docs.polymarket.com/api-reference/introduction`
- Polymarket order creation: `https://docs.polymarket.com/trading/orders/create`
- Polymarket orderbook and WebSocket docs: `https://docs.polymarket.com/trading/orderbook`
- Polymarket geographic restrictions: `https://docs.polymarket.com/api-reference/geoblock`
- Polymarket rate limits: `https://docs.polymarket.com/api-reference/rate-limits`
- Ollama OpenAI compatibility: `https://docs.ollama.com/api/openai-compatibility`
- OpenRouter OpenAI SDK compatibility: `https://openrouter.ai/docs/guides/community/openai-sdk`
- SearXNG search API: `https://docs.searxng.org/dev/search_api`
- Lightpanda docs: `https://lightpanda.io/docs/`
- Daytona sandboxes: `https://www.daytona.io/docs/en/sandboxes/`
- Daytona Python SDK: `https://www.daytona.io/docs/en/python-sdk/`
