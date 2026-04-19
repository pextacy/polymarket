# Autonomous Polymarket Trader — CLAUDE.md

## Project Overview

This is an autonomous research and trading agent for Polymarket prediction markets. The goal is to evolve a prototype into a continuously running, production-grade trading platform that discovers markets, gathers evidence, estimates probabilities, and executes trades with strict risk controls.

**Current state:** Early prototype with basic autonomous path in `scripts/python/cli.py` and `agents/application/trade.py`. Not safe or complete for unattended operation.

**Target state:** A fully observable, paper-first autonomous trading system with isolated execution, self-hosted search, and headless browsing.

---

## Architecture

### Core Subsystems

```
Market Discovery → Research Pipeline → Intelligence Layer → Strategy Engine → Broker Layer
       ↓                  ↓                   ↓                  ↓               ↓
  Gamma API          SearXNG        Ollama/OpenAI-Compat    Risk Engine     PaperBroker
  CLOB Data         Lightpanda         Structured JSON      ExecutionPlan   PolymarketBroker
  Data API           Evidence           Forecast/Score      Sizing/Edge
```

### Control Plane vs Worker Plane

- **Control server:** scheduler, database, metrics, alerting, sandbox lifecycle management
- **Worker sandboxes (Daytona):** market scan, search/browse, forecast, execution planning

---

## Technology Stack

| Component | Technology |
|-----------|-----------|
| LLM Access | Ollama by default, OpenRouter or other OpenAI-compatible backends optional |
| Web Search | SearXNG (self-hosted) |
| Headless Browser | Lightpanda (CDP-compatible) |
| Isolated Execution | Daytona sandboxes |
| Database | SQLite (local dev) → Postgres (server) |
| Queue/Cache | Redis (optional) |
| Metrics | Prometheus + Grafana |

### Model Provider Config (env vars)

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
# Optional backends:
OPENROUTER_API_KEY=...
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1
LLM_MODEL=...
# Per-task model overrides:
LLM_MODEL_RANKING=...
LLM_MODEL_FORECASTING=...
LLM_MODEL_EXTRACTION=...

SEARCH_PROVIDER=searxng
SEARXNG_BASE_URL=...
SEARXNG_TIMEOUT_SECONDS=...
```

**Never use direct OpenAI keys as the default.** Local Ollama is the default LLM backend, with OpenRouter available as an override.

---

## Safety & Compliance Rules (HARD REQUIREMENTS)

### Trading Mode

- Default mode is always **`paper`** — never `live`
- Live mode is opt-in only, disabled by default
- Before any live order: geoblock check → compliance → config validation → key validation → balance validation → risk engine → execution venue sanity

### Jurisdiction Gate

- Must call Polymarket geoblock endpoint before enabling any live order flow
- If blocked → hard fail into paper-only mode
- No bypass behavior allowed anywhere in code or docs

### Pre-Trade Safety Checklist (live mode)

1. Compliance checks pass
2. Configuration valid
3. API keys present
4. Balance and allowance sufficient
5. Risk engine approves
6. Execution venue sanity pass

---

## Domain Data Models

Use explicit typed models — no free-form string parsing or tuple-heavy flows:

```python
MarketSnapshot
EvidenceItem
Forecast          # includes: confidence, rationale, sources, fair_probability, timestamp
OpportunityScore
TradeIdea
ExecutionPlan     # must exist before any broker action
OrderRecord
FillRecord
PositionState
PortfolioState
RiskDecision
RunRecord
```

All model outputs must be **structured JSON only** — reject malformed outputs.

---

## Risk Engine Requirements

The risk engine must enforce all of these before approving any trade:

- Max notional per market
- Max portfolio exposure
- Max category exposure
- Max daily loss
- Max open positions
- Max open orders
- Stale signal rejection
- No-trade windows near expiry/resolution (configurable)
- Cooldown after repeated losses or execution errors

---

## Research Pipeline

For each market candidate:

1. Generate search queries
2. Fetch results from SearXNG (JSON output, normalized schema)
3. Browse selected pages with Lightpanda for JS-heavy content
4. Extract evidence into structured `EvidenceItem` records
5. Deduplicate sources, filter low-signal spam

SearXNG result schema:
```python
{
  "title": str,
  "url": str,
  "snippet": str,
  "source": str,
  "published_at": str,
  "score": float
}
```

---

## Broker Layer

### PaperBroker

- Simulate fills based on configured fill logic
- Track: positions, cash, realized PnL, unrealized PnL
- Log every order, fill, and cancellation

### PolymarketBroker (live — gated)

- Verify geoblock and mode gates first
- Validate: token id, side, tick size, order type, balances, allowances
- Support `FOK` and `FAK` order types
- Persist all exchange responses for reconciliation

---

## CLI Commands

```bash
# Core (Milestone 1)
python -m polymarket_trader.cli scan
python -m polymarket_trader.cli paper-trade
python -m polymarket_trader.cli report
python -m polymarket_trader.cli positions
python -m polymarket_trader.cli runs
python -m polymarket_trader.cli risk-status
python -m polymarket_trader.cli sandbox-status
python -m polymarket_trader.cli sandbox-scan
python -m polymarket_trader.cli sandbox-paper-trade-once

# Later (Milestone 4+)
python -m polymarket_trader.cli live-trade       # requires explicit opt-in
python -m polymarket_trader.cli resume-run
python -m polymarket_trader.cli reconcile
```

---

## Milestones

### M1 — Paper Trader Foundation
- Refactored orchestrator with typed domain models
- Provider abstraction + local-first OpenAI-compatible integration
- PaperBroker + persistent run logging
- Risk engine v1
- Real tests covering: pricing, sizing, risk, execution guards
- Exit: full paper loop end-to-end, no live path reachable by default

### M2 — Research Stack Upgrade
- Integrated SearXNG client (replaces Tavily proof-of-concept)
- Lightpanda browser worker
- Evidence extraction + freshness/dedupe logic
- Exit: agent gathers evidence from search + rendered pages, stores artifacts per run

### M3 — Continuous Runtime
- Daytona worker integration
- Control server orchestration + scheduling
- Health checks, retry, recovery framework
- Exit: remote sandbox scan and paper-trade workers run through Daytona, then unattended paper mode stays stable for 7+ days

### M4 — Live Trading Readiness
- Live broker hardening + reconciliation
- Kill switch + alerting
- Exit: all live checks pass in eligible environment, live mode opt-in only

---

## Implementation Order

1. Replace `ChatOpenAI` calls with provider abstraction + Ollama default
2. Refactor trader into explicit stages with typed objects
3. Add PaperBroker + persistent run records
4. Add risk engine + structured reporting
5. Replace Tavily with SearXNG client
6. Add Lightpanda browser worker
7. Add Daytona orchestration
8. Add server deployment + health checks for 24/7 ops
9. Harden live broker **only after** paper mode is stable

---

## Code Conventions

- **No unbounded recursion** — all retry logic must be bounded with backoff
- **Structured outputs only** — every machine-consumed decision must be typed JSON, never free-form strings
- **Deterministic guards** around all non-deterministic model calls
- **Strategy logic separate from infrastructure logic**
- **No secrets in repo** — use `.env` files, never commit keys
- Paper mode must be fully functional even when live mode is blocked

---

## Key External APIs

- Polymarket API: `https://docs.polymarket.com/api-reference/introduction`
- Polymarket Geoblock: `https://docs.polymarket.com/api-reference/geoblock`
- Polymarket Orders: `https://docs.polymarket.com/trading/orders/create`
- Ollama OpenAI compatibility: `https://docs.ollama.com/api/openai-compatibility`
- SearXNG: `https://docs.searxng.org/dev/search_api`
- Lightpanda: `https://lightpanda.io/docs/`
- Daytona Python SDK: `https://www.daytona.io/docs/en/python-sdk/`

---

## Open Questions (as of 2026-04-19)

- Which local models should be used for ranking vs forecasting vs extraction?
- Migrate embeddings off OpenAI now or defer until after chat-model migration?
- SearXNG + Lightpanda on same host as control server or separate internal services?
- One long-lived sandbox or short-lived task sandboxes for 24/7 runtime?
- SQLite local + Postgres server, or Postgres everywhere?
- Alerting channel: email, Slack, Telegram, or Discord?

---

## Non-Goals for V1

- Fully autonomous live trading in blocked jurisdictions
- High-frequency market making
- Multi-exchange support
- Historical backtesting (years of data)
- Complex portfolio optimization (hundreds of simultaneous positions)
- Mobile app or end-user GUI
