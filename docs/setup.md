# Setup Guide

## Requirements

- Python 3.11+
- Docker + Docker Compose (for SearXNG, Lightpanda, PostgreSQL, Redis)
- An OpenRouter API key (get one at https://openrouter.ai)

---

## 1. Clone and Install

```bash
# Install in editable mode with dev dependencies
python3.11 -m pip install -e ".[dev]"

# Verify the CLI is available
polymarket --help
```

---

## 2. Configure Environment

```bash
cp .env.example .env
```

Open `.env` and fill in the required values:

```env
# Required
OPENROUTER_API_KEY=sk-or-v1-...

# Optional — defaults work for local dev
LLM_MODEL=openai/gpt-4o
TRADING_MODE=paper
```

All other settings have safe defaults. See [configuration.md](configuration.md) for the full reference.

---

## 3. Start Infrastructure Services

```bash
docker-compose up -d searxng
```

Wait for SearXNG to be healthy:

```bash
curl http://localhost:8888/search?q=test&format=json
```

Lightpanda and PostgreSQL are optional for local development. The system falls back to:
- Plain HTTP fetch if Lightpanda is unreachable
- SQLite if `DATABASE_URL` points to a local file (default)

---

## 4. Verify Setup

Run a market scan to confirm all connections work:

```bash
polymarket scan --top 10
```

This calls:
1. Polymarket Gamma API (no auth required)
2. Polymarket CLOB API (no auth required for read)
3. OpenRouter API (requires key)
4. SearXNG (requires the Docker service)

If you see a table of markets, the setup is working.

---

## 5. Run Paper Trading

Single cycle:

```bash
polymarket paper-trade --once
```

Continuous loop (runs every `SCAN_INTERVAL_SECONDS`, default 15 minutes):

```bash
polymarket paper-trade
```

Logs are written to `logs/trader.log`. The database is created automatically at `polymarket_trader.db`.

---

## 6. Check Results

```bash
# Recent run history
polymarket runs

# Fills for a specific run (copy run_id from 'runs' output)
polymarket report <run_id>

# Risk limits currently configured
polymarket risk-status
```

---

## Production Setup (PostgreSQL)

1. Start the full stack:

```bash
POSTGRES_PASSWORD=yourpassword docker-compose up -d
```

2. Update `.env`:

```env
DATABASE_URL=postgresql+asyncpg://trader:yourpassword@localhost:5432/polymarket_trader
```

3. Install the async PostgreSQL driver:

```bash
pip install asyncpg
```

---

## Enabling Lightpanda

1. Start the service:

```bash
docker-compose up -d lightpanda
```

2. Set in `.env`:

```env
LIGHTPANDA_WS_URL=ws://localhost:9222
```

The research pipeline automatically uses Lightpanda for JavaScript-heavy pages when this URL is reachable. If the service is down, it falls back to plain HTTP without crashing.

---

## Live Trading Prerequisites

Live trading requires additional setup and is disabled by default (`TRADING_MODE=paper`).

**Before enabling live trading:**

1. Verify you are eligible under Polymarket Terms of Service
2. Create a Polymarket account and fund it with USDC on Polygon
3. Export your wallet private key
4. Set in `.env`:

```env
TRADING_MODE=live
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_PROXY_ADDRESS=0x...
```

The system will call the geoblock endpoint on startup. If your region is blocked, it will refuse to place any live orders and stay in paper mode.

See [trading-modes.md](trading-modes.md) for full details.

---

## Running Tests

```bash
python3.11 -m pytest tests/ -v
```

No external services are required to run the test suite. All tests use in-memory state.
