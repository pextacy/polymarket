# Autonomous Polymarket Trader PRD

## Document Status

- Status: Draft v1
- Date: 2026-04-19
- Repo: 
- Scope: End-to-end product and technical requirements for turning the current prototype into a continuously running autonomous trading system

## 1. Overview

This project will evolve the current Polymarket agent prototype into a production-oriented autonomous trading platform with:

- paper trading first, live trading later
- structured research and decision pipelines
- self-hosted web search using SearXNG
- headless web browsing using Lightpanda
- model access through OpenRouter instead of direct OpenAI keys
- isolated agent execution inside Daytona sandboxes
- optional 24/7 server orchestration and monitoring

The current repo already contains a basic autonomous path in `scripts/python/cli.py` and `agents/application/trade.py`, but it is not safe or complete enough for unattended operation. It lacks a risk engine, persistent state, proper execution guards, reconciliation, and meaningful tests.

## 2. Problem

The existing implementation is a prototype with the following limitations:

- model access is hard-wired to `ChatOpenAI`
- embeddings are hard-wired to OpenAI embeddings
- search is a proof-of-concept Tavily script, not an integrated search subsystem
- trade selection is mostly generic prompt filtering rather than a defined edge model
- exceptions recurse indefinitely
- there is no paper broker, no portfolio state, and no reporting layer
- there is no reliable 24/7 runtime model
- tests are placeholders and do not validate trading behavior

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
   - OpenRouter-backed LLM access for ranking, summarization, forecasting, and extraction
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

### 10.1 Replace direct OpenAI usage with OpenRouter

Current state:

- `agents/application/executor.py` uses `ChatOpenAI`
- `agents/connectors/chroma.py` uses `OpenAIEmbeddings`
- `.env.example` expects `OPENAI_API_KEY`

Target state:

- replace direct OpenAI credential dependency with `OPENROUTER_API_KEY`
- route chat model calls through OpenRouter using OpenAI-compatible base URL
- introduce a model provider abstraction so model backend is configurable
- preserve the option to use OpenAI-compatible SDK clients where practical

Requirements:

- add provider config fields:
  - `LLM_PROVIDER=openrouter`
  - `OPENROUTER_API_KEY`
  - `OPENROUTER_BASE_URL=https://openrouter.ai/api/v1`
  - `LLM_MODEL`
- optionally retain `OPENAI_API_KEY` only as a fallback provider, not as the default
- support model overrides per task type:
  - ranking model
  - forecasting model
  - extraction model

Notes:

- OpenRouter is OpenAI-compatible and can be used via base URL switching
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

Add CLI commands for:

- `scan`
- `paper-trade`
- `report`
- `positions`
- `runs`
- `risk-status`
- `sandbox-status`

Optional later:

- `live-trade`
- `resume-run`
- `reconcile`

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

### Milestone 1: Paper Trader Foundation

Deliverables:

- refactored orchestrator
- typed domain models
- provider abstraction for LLM access
- OpenRouter integration for chat models
- paper broker
- persistent run logging
- risk engine v1
- real tests
- CLI commands for `scan`, `paper-trade`, `report`

Exit criteria:

- full paper-trading loop runs end-to-end
- no live execution path is reachable by default
- test suite covers critical decision logic

### Milestone 2: Research Stack Upgrade

Deliverables:

- integrated SearXNG search client
- Lightpanda browser worker
- evidence extraction pipeline
- source freshness and dedupe logic
- search and browse budget controls

Exit criteria:

- agent can gather evidence from search plus rendered pages
- research artifacts are stored per run

### Milestone 3: Continuous Runtime

Deliverables:

- Daytona worker integration
- control server orchestration
- queueing and scheduling
- health checks
- retry and recovery framework
- server deployment docs

Exit criteria:

- system runs unattended in paper mode for at least 7 days

### Milestone 4: Live Trading Readiness

Deliverables:

- live broker hardening
- reconciliation
- allowance and balance checks
- execution safety gates
- kill switch
- alerting

Exit criteria:

- all live trading checks pass in eligible environment
- live mode remains opt-in and disabled by default

## 17. Acceptance Criteria

The project is considered successful for the first production-grade release when:

- the paper trading system is stable and fully observable
- OpenRouter is the default model backend
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

- which specific OpenRouter models should be used for ranking, forecasting, and extraction?
- should embeddings also move away from OpenAI immediately, or can that be deferred until after the chat-model migration?
- should SearXNG and Lightpanda live on the same host as the control server or behind separate internal services?
- should the first 24/7 runtime use one long-lived sandbox or short-lived task sandboxes managed by the control server?
- what database should be the default for persisted state: SQLite for local dev and Postgres for server, or Postgres everywhere?
- what alerting channel is preferred for production: email, Slack, Telegram, or Discord?

## 20. Immediate Implementation Plan

Order of execution:

1. replace direct OpenAI chat calls with a provider abstraction and OpenRouter default
2. refactor the trader into explicit stages and typed objects
3. add paper broker and persistent run records
4. add risk engine and structured reporting
5. replace Tavily proof-of-concept with SearXNG client
6. add Lightpanda browser worker for dynamic page retrieval
7. add Daytona orchestration for isolated worker execution
8. add server deployment, health checks, and 24/7 operations
9. harden live broker only after paper mode is stable

## 21. External References

These informed the architecture as of 2026-04-19:

- Polymarket API introduction: `https://docs.polymarket.com/api-reference/introduction`
- Polymarket order creation: `https://docs.polymarket.com/trading/orders/create`
- Polymarket orderbook and WebSocket docs: `https://docs.polymarket.com/trading/orderbook`
- Polymarket geographic restrictions: `https://docs.polymarket.com/api-reference/geoblock`
- Polymarket rate limits: `https://docs.polymarket.com/api-reference/rate-limits`
- OpenRouter OpenAI SDK compatibility: `https://openrouter.ai/docs/guides/community/openai-sdk`
- OpenRouter API keys: `https://openrouter.ai/docs/api-keys`
- SearXNG search API: `https://docs.searxng.org/dev/search_api`
- Lightpanda docs: `https://lightpanda.io/docs/`
- Daytona sandboxes: `https://www.daytona.io/docs/en/sandboxes/`
- Daytona Python SDK: `https://www.daytona.io/docs/en/python-sdk/`