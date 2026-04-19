# Autonomous Polymarket Trader — CLAUDE.md

## Project Overview

This is an autonomous research and trading agent for Polymarket prediction markets. The goal is to evolve a prototype into a continuously running, production-grade trading platform that discovers markets, gathers evidence, estimates probabilities, and executes trades with strict risk controls.

**Current state (2026-04-20):** M1 + M2 complete. Full paper trading loop runs end-to-end. SearXNG + Lightpanda integrated. Daytona sandbox workers operational. Live broker exists with geoblock + balance checks. 39 passing tests. All persistence paths wired (12 DB tables).

**Remaining for production:** Health checks, Prometheus metrics, alerting channel, kill switch. See `docs/prd.md` section 20.

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
# All implemented and working
python -m polymarket_trader.cli scan                     # rank live markets
python -m polymarket_trader.cli paper-trade [--once]     # paper loop
python -m polymarket_trader.cli live-trade  [--once]     # live loop (gated)
python -m polymarket_trader.cli report <run_id>          # fills for a run
python -m polymarket_trader.cli positions [--run-id X]   # positions from DB
python -m polymarket_trader.cli runs [--limit N]         # run history
python -m polymarket_trader.cli risk-status              # show risk limits
python -m polymarket_trader.cli reconcile <run_id>       # fill vs position drift
python -m polymarket_trader.cli sandbox-status           # Daytona sandbox list
python -m polymarket_trader.cli sandbox-scan             # remote scan in sandbox
python -m polymarket_trader.cli sandbox-paper-trade-once # remote paper trade

# Not yet implemented
# python -m polymarket_trader.cli resume-run             # M4+
```

---

## Milestones

### M1 — Paper Trader Foundation ✅ COMPLETE
- Refactored orchestrator with typed domain models
- Provider abstraction + Ollama default
- PaperBroker + full persistence (12 DB tables, all calls wired)
- Risk engine v1 — all 10 rules + cooldown feedback loop bağlı
- 39 real tests
- Exit criteria met: paper loop end-to-end, no live path reachable by default

### M2 — Research Stack Upgrade ✅ COMPLETE
- SearXNG client — JSON output, retry, 3-format date parsing
- Lightpanda browser worker — CDP + HTTP fallback
- Evidence pipeline — dedup (URL + MD5 snippet), 168h freshness
- Evidence caching — 6h window in DB; orchestrator skips pipeline on cache hit
- Exit criteria met: evidence stored per run, cache avoids redundant fetches

### M3 — Continuous Runtime 🔶 PARTIAL
- ✅ Daytona sandbox workers operational
- ✅ `run_continuous()` loop
- ✅ `sandbox-scan`, `sandbox-paper-trade-once` CLI commands
- ❌ Health check endpoint
- ❌ Prometheus metrics + Grafana dashboard
- ❌ 7-day stability run not completed

### M4 — Live Trading Readiness 🔶 PARTIAL
- ✅ `PolymarketBroker` with geoblock + balance + allowance preflight
- ✅ `live-trade` CLI command
- ✅ `reconcile` CLI command
- ❌ Kill switch mechanism
- ❌ Alerting integration (Telegram / email)
- ❌ `resume-run` command
- ❌ Live environment end-to-end test

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

## Open Questions (as of 2026-04-20)

- Which local models for ranking vs forecasting vs extraction? (use `LLM_MODEL_*` overrides to tune)
- ~~Migrate embeddings off OpenAI?~~ Resolved — embeddings removed entirely from trading path
- SearXNG + Lightpanda: same host or separate services? (docker-compose co-locates; separate for prod)
- One long-lived sandbox or short-lived task sandboxes? (deferred to M3 ops work)
- ~~SQLite vs Postgres everywhere?~~ Resolved — SQLite for dev, asyncpg for prod, same ORM
- Alerting channel? (Telegram recommended — required for M4 exit)
- How to approve USDC CTF Exchange allowance for live trading? (need helper script)

---

## Non-Goals for V1

- Fully autonomous live trading in blocked jurisdictions
- High-frequency market making
- Multi-exchange support
- Historical backtesting (years of data)
- Complex portfolio optimization (hundreds of simultaneous positions)
- Mobile app or end-user GUI
