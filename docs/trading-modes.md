# Trading Modes

## Overview

The system supports two trading modes: `paper` and `live`. The default is always `paper`. Live mode requires explicit opt-in and passes a mandatory pre-flight checklist before any order is submitted.

---

## Paper Mode

```env
TRADING_MODE=paper
```

Paper mode simulates the full trading loop using an in-memory broker. No real money moves. It is safe to run continuously and in any region.

### What paper mode does

- Maintains a simulated cash balance (starts at `PAPER_INITIAL_CASH`)
- Fills orders immediately at `estimated_fill_price` with configured slippage
- Tracks positions, average entry price, realised PnL, and daily loss
- Logs every order and fill to the database
- Enforces all risk limits — the risk engine runs identically in both modes

### What paper mode does not do

- Does not connect to a Polymarket wallet
- Does not submit any orders to the CLOB
- Does not require `POLYMARKET_PRIVATE_KEY` or `POLYMARKET_PROXY_ADDRESS`

### Paper fill simulation

```
fill_price = limit_price × (1 + PAPER_FILL_SLIPPAGE_BPS / 10_000)   # for BUY
fill_price = limit_price × (1 - PAPER_FILL_SLIPPAGE_BPS / 10_000)   # for SELL
```

Fills are always capped to the range (0.001, 0.999).

---

## Live Mode

```env
TRADING_MODE=live
POLYMARKET_PRIVATE_KEY=0x...
POLYMARKET_PROXY_ADDRESS=0x...
```

Live mode connects to Polymarket's CLOB and places real orders using real USDC on Polygon.

### Mandatory pre-flight checks

Before any live order is attempted, `PolymarketBroker.preflight()` runs:

1. **Geoblock check** — calls `GET /geo-blocked` on the CLOB API. If the response indicates blocking, the system raises `RuntimeError` and does not place any orders. There is no bypass.
2. **Credential derivation** — derives API credentials from the private key using EIP-712 signing. Fails fast if the key is missing or invalid.

### Pre-trade safety gates

Every live order must pass all of these before submission:

```
Compliance check (geoblock)
  → Config validation (mode, keys present)
    → Risk engine (all 10 rules)
      → ExecutionPlan validation (tick size, size limits)
        → ClobClient order submission
```

If any gate fails, the order is not submitted. The failure is logged and counted in the run record.

### Live order types

Supported order types from the PRD:

| Type | Behaviour |
|------|-----------|
| `FOK` (Fill-or-Kill) | Must fill entirely immediately or the order is cancelled |
| `FAK` (Fill-and-Kill) | Fills as much as possible immediately, cancels the rest |
| `GTC` (Good-Till-Cancelled) | Rests on the book until filled or cancelled |

The planner currently uses `FOK` by default for predictable execution.

### Live position tracking

`PolymarketBroker.get_portfolio()` fetches real positions and balances from the CLOB API:
- `get_positions()` → maps to `PositionState` objects
- `get_balance_allowance()` → returns real USDC cash balance

---

## Switching Modes

You can override the configured mode at the CLI level:

```bash
polymarket --mode paper paper-trade
polymarket --mode live paper-trade   # NOT recommended — use env var instead
```

Using the `--mode` flag overrides the `.env` setting for that session only.

---

## Jurisdiction Compliance

Polymarket's Terms of Service prohibit use from certain regions including the United States. The system enforces this via geoblock checks. If you are in a restricted region:

- Live mode will refuse to operate
- Paper mode continues to work fully
- No hidden bypass is present anywhere in the codebase

You are responsible for ensuring your use complies with applicable laws and Polymarket's Terms of Service.

---

## Mode Comparison

| Feature | Paper | Live |
|---------|-------|------|
| Real orders on Polymarket | No | Yes |
| Real USDC required | No | Yes |
| Geoblock check | No | Yes (hard fail) |
| Risk engine active | Yes | Yes |
| Position tracking | In-memory | CLOB API |
| PnL tracking | Simulated | Real |
| Fill simulation | Yes | No (real fills) |
| Private key required | No | Yes |
| Safe to run anywhere | Yes | Only eligible regions |
