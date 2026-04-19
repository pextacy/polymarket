# Configuration Reference

All settings are loaded from the `.env` file (or environment variables) via `config.py`. Settings are case-insensitive.

---

## LLM Provider

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_PROVIDER` | `ollama` | LLM backend. Supported: `ollama`, `openrouter`, `openai_compatible`. |
| `OLLAMA_BASE_URL` | `http://localhost:11434/v1` | Local Ollama OpenAI-compatible base URL. |
| `OLLAMA_API_KEY` | _(optional)_ | Ignored by local Ollama, but accepted for gateway setups. |
| `OPENROUTER_API_KEY` | _(optional)_ | Required only when `LLM_PROVIDER=openrouter`. |
| `OPENROUTER_BASE_URL` | `https://openrouter.ai/api/v1` | OpenRouter API base URL. |
| `OPENAI_COMPATIBLE_BASE_URL` | `http://localhost:8000/v1` | Base URL for another OpenAI-compatible server such as vLLM. |
| `OPENAI_COMPATIBLE_API_KEY` | _(optional)_ | API key sent to the OpenAI-compatible server. |
| `LLM_MODEL` | `llama3.2:3b` | Default model for all tasks. |
| `LLM_MODEL_RANKING` | _(uses LLM_MODEL)_ | Model used to rank markets by researchability. |
| `LLM_MODEL_FORECASTING` | _(uses LLM_MODEL)_ | Model used to estimate fair probabilities. |
| `LLM_MODEL_EXTRACTION` | _(uses LLM_MODEL)_ | Model used to generate search queries. |

**Model selection guidance:**
- For local development, start with a small Ollama model such as `llama3.2:3b`
- Ranking and extraction can use a smaller model than forecasting
- If you need more capability than Ollama on your machine can provide, switch to `openai_compatible` or `openrouter`

---

## Search

| Variable | Default | Description |
|----------|---------|-------------|
| `SEARCH_PROVIDER` | `searxng` | Search backend. Only `searxng` is supported. |
| `SEARXNG_BASE_URL` | `http://localhost:8888` | URL of your SearXNG instance. |
| `SEARXNG_TIMEOUT_SECONDS` | `15` | HTTP timeout for search requests. |

---

## Browser (Lightpanda)

| Variable | Default | Description |
|----------|---------|-------------|
| `LIGHTPANDA_WS_URL` | `ws://localhost:9222` | WebSocket/CDP URL for Lightpanda. |
| `LIGHTPANDA_TIMEOUT_SECONDS` | `30` | Timeout for page fetch requests. |
| `LIGHTPANDA_MAX_PAGE_BYTES` | `2097152` | Max response size in bytes (2 MB). |

If Lightpanda is unreachable, the research pipeline silently falls back to plain HTTP.

---

## Polymarket APIs

| Variable | Default | Description |
|----------|---------|-------------|
| `GAMMA_BASE_URL` | `https://gamma-api.polymarket.com` | Gamma API for market discovery. |
| `CLOB_BASE_URL` | `https://clob.polymarket.com` | CLOB API for order book data and order execution. |
| `DATA_API_BASE_URL` | `https://data-api.polymarket.com` | Data API for account state. |
| `POLYMARKET_CHAIN_ID` | `137` | Polygon mainnet chain ID. Do not change. |

---

## Live Trading Keys

These are only required when `TRADING_MODE=live`.

| Variable | Default | Description |
|----------|---------|-------------|
| `POLYMARKET_PRIVATE_KEY` | _(empty)_ | Wallet private key (hex, with or without 0x prefix). |
| `POLYMARKET_PROXY_ADDRESS` | _(empty)_ | Polymarket proxy contract address for your account. |

**Never commit these values.** Keep them in `.env` which is in `.gitignore`.

---

## Trading Mode

| Variable | Default | Description |
|----------|---------|-------------|
| `TRADING_MODE` | `paper` | `paper` or `live`. Default is always `paper`. |

---

## Risk Limits

All monetary limits are in USDC.

| Variable | Default | Description |
|----------|---------|-------------|
| `RISK_MAX_NOTIONAL_PER_MARKET` | `50.0` | Maximum USDC per single market position. |
| `RISK_MAX_PORTFOLIO_EXPOSURE` | `500.0` | Maximum total USDC across all open positions. |
| `RISK_MAX_CATEGORY_EXPOSURE` | `150.0` | Maximum USDC exposure within a single market category. |
| `RISK_MAX_DAILY_LOSS` | `100.0` | Maximum realised loss in a single calendar day. |
| `RISK_MAX_OPEN_POSITIONS` | `20` | Maximum number of concurrent open positions. |
| `RISK_MAX_OPEN_ORDERS` | `40` | Maximum number of orders in pending state. |
| `RISK_SIGNAL_STALENESS_SECONDS` | `3600` | Maximum age of a forecast before the trade is rejected. |
| `RISK_EXPIRY_NO_TRADE_HOURS` | `2` | Do not trade markets expiring within this many hours. |
| `RISK_COOLDOWN_AFTER_LOSSES` | `3` | Consecutive losses before a per-market cooldown triggers. |
| `RISK_COOLDOWN_DURATION_SECONDS` | `3600` | Duration of the cooldown period (1 hour). |

See [risk-engine.md](risk-engine.md) for the full rule evaluation order.

---

## Paper Broker

| Variable | Default | Description |
|----------|---------|-------------|
| `PAPER_INITIAL_CASH` | `10000.0` | Starting USDC balance for paper trading. |
| `PAPER_FILL_SLIPPAGE_BPS` | `20` | Simulated slippage on fills in basis points (0.20%). |
| `LIVE_FILL_SLIPPAGE_BPS` | `10` | Expected slippage for live order fill estimation (0.10%). |

---

## Persistence

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite+aiosqlite:///./polymarket_trader.db` | SQLAlchemy async database URL. |

For production use PostgreSQL:
```
DATABASE_URL=postgresql+asyncpg://trader:password@localhost:5432/polymarket_trader
```

---

## Scan Cycle

| Variable | Default | Description |
|----------|---------|-------------|
| `SCAN_INTERVAL_SECONDS` | `900` | Seconds between scan cycles in continuous mode (15 min). |
| `SCAN_MARKET_LIMIT` | `100` | Maximum markets to fetch from Gamma API per cycle. |
| `SCAN_MIN_LIQUIDITY_USDC` | `500.0` | Skip markets with liquidity below this threshold. |
| `SCAN_MIN_VOLUME_24H_USDC` | `1000.0` | Skip markets with 24h volume below this threshold. |
| `SCAN_MAX_RESEARCH_SOURCES` | `5` | Number of search results to gather per query. |
| `SCAN_MIN_EDGE_BPS` | `200` | Minimum edge in basis points to consider a market worth trading. |

---

## Observability

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `LOG_FILE` | `logs/trader.log` | Log file path. Rotated at 50 MB, retained 30 days. |

---

## Infrastructure (docker-compose)

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_PASSWORD` | `changeme` | PostgreSQL password used by docker-compose. |
| `DAYTONA_API_KEY` | _(empty)_ | Daytona API key used by sandbox commands. |

---

## Daytona Runtime

| Variable | Default | Description |
|----------|---------|-------------|
| `DAYTONA_API_URL` | `https://app.daytona.io/api` | Daytona API base URL. |
| `DAYTONA_TARGET` | _(empty)_ | Optional Daytona target region or runner name. |
| `DAYTONA_SANDBOX_NAME_PREFIX` | `polymarket-trader` | Prefix used for sandbox names and project labels. |
| `DAYTONA_SANDBOX_SNAPSHOT` | _(empty)_ | Optional Daytona snapshot name to create sandboxes from. |
| `DAYTONA_SANDBOX_AUTO_STOP_MINUTES` | `15` | Auto-stop interval in minutes. `0` disables auto-stop. |
| `DAYTONA_SANDBOX_COMMAND_TIMEOUT_SECONDS` | `1800` | Timeout used for remote bootstrap and worker commands. |
| `DAYTONA_PROJECT_REPO_URL` | _(auto-detected)_ | Repo URL cloned into the sandbox. Falls back to local `git remote get-url origin`. |
| `DAYTONA_PROJECT_REF` | _(auto-detected)_ | Branch or commit checked out in the sandbox. Falls back to the local current branch or `HEAD` commit. |
| `DAYTONA_PROJECT_DIR` | `/home/daytona/polymarket` | Path inside the sandbox where the repo is cloned and executed. |

The remote worker commands always pass the current trader configuration into the sandbox as process environment variables, but they deliberately exclude the Daytona credentials themselves. In `paper` mode they also exclude `POLYMARKET_PRIVATE_KEY` and `POLYMARKET_PROXY_ADDRESS`.
