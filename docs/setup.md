# Setup Guide

## Requirements

- Python 3.11+
- Docker + Docker Compose (for Ollama, SearXNG, Lightpanda, PostgreSQL, Redis)
- A local Ollama model for the default setup

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
# Local-first default
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434/v1
LLM_MODEL=llama3.2:3b
TRADING_MODE=paper
```

All other settings have safe defaults. `openrouter` and other OpenAI-compatible backends remain available as explicit overrides. See [configuration.md](configuration.md) for the full reference.

---

## 3. Start Infrastructure Services

```bash
docker-compose up -d ollama searxng
```

Pull the default model into the local Ollama instance:

```bash
docker exec -it polymarket-ollama ollama pull llama3.2:3b
```

Wait for Ollama and SearXNG to be healthy:

```bash
curl http://localhost:11434/api/tags
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
3. Local Ollama via OpenAI-compatible API
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

## Optional: Alternate LLM Backends

To use OpenRouter instead of local Ollama:

```env
LLM_PROVIDER=openrouter
OPENROUTER_API_KEY=...
LLM_MODEL=openai/gpt-4o-mini
```

To use another OpenAI-compatible local server such as vLLM:

```env
LLM_PROVIDER=openai_compatible
OPENAI_COMPATIBLE_BASE_URL=http://localhost:8000/v1
OPENAI_COMPATIBLE_API_KEY=local
LLM_MODEL=your-model-name
```

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
