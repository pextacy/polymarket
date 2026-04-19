# Risk Engine

## Overview

The risk engine (`risk/engine.py`) evaluates every `ExecutionPlan` before it reaches the broker. It enforces ten hard rules. The first failing rule immediately rejects the trade — no further rules are checked.

The engine maintains in-memory state across trades (cooldown tracking, loss streaks). It is instantiated once per `Orchestrator` and persists for the lifetime of the process.

---

## Rule Evaluation Order

```
1. Global cooldown
2. Per-market cooldown
3. Signal staleness
4. Expiry proximity
5. Notional per market
6. Portfolio exposure
7. Category exposure
8. Daily loss
9. Open positions
10. Open orders
```

---

## Rules

### 1. Global Cooldown

**Config:** `RISK_COOLDOWN_AFTER_LOSSES`, `RISK_COOLDOWN_DURATION_SECONDS`

Triggered when the number of consecutive losses across all markets reaches `RISK_COOLDOWN_AFTER_LOSSES × 2`. The engine enters a global cooldown for `RISK_COOLDOWN_DURATION_SECONDS × 2` seconds. No trades of any kind are allowed during this period.

The global consecutive loss counter resets to zero when the cooldown fires.

---

### 2. Per-Market Cooldown

**Config:** `RISK_COOLDOWN_AFTER_LOSSES`, `RISK_COOLDOWN_DURATION_SECONDS`

Each market tracks its own loss streak. When the streak for a single market reaches `RISK_COOLDOWN_AFTER_LOSSES`, that market enters cooldown for `RISK_COOLDOWN_DURATION_SECONDS`. Only trades on that specific market are blocked.

Call `RiskEngine.record_loss(condition_id)` after a losing fill. Call `record_win(condition_id)` after a profitable fill to reset the streak.

---

### 3. Signal Staleness

**Config:** `RISK_SIGNAL_STALENESS_SECONDS` (default: 3600)

Rejects a plan if `datetime.utcnow() - plan.planned_at > RISK_SIGNAL_STALENESS_SECONDS`. This prevents executing on forecasts that may no longer reflect current evidence.

---

### 4. Expiry Proximity

**Config:** `RISK_EXPIRY_NO_TRADE_HOURS` (default: 2)

Rejects a trade if the market resolves within `RISK_EXPIRY_NO_TRADE_HOURS` hours. This avoids adverse selection near resolution, when prices are most volatile and hard to hedge.

Markets with no `end_date` are always allowed.

---

### 5. Notional Per Market

**Config:** `RISK_MAX_NOTIONAL_PER_MARKET` (default: $50)

Rejects if `plan.size_usdc > RISK_MAX_NOTIONAL_PER_MARKET`.

This is a hard cap on the dollar amount of any single trade, regardless of Kelly sizing or portfolio state.

---

### 6. Portfolio Exposure

**Config:** `RISK_MAX_PORTFOLIO_EXPOSURE` (default: $500)

Rejects if `total_exposure + plan.size_usdc > RISK_MAX_PORTFOLIO_EXPOSURE`.

`total_exposure` is the sum of `position.size_tokens × position.avg_entry_price` across all open positions.

---

### 7. Category Exposure

**Config:** `RISK_MAX_CATEGORY_EXPOSURE` (default: $150)

Rejects if the total exposure in `market.category` plus `plan.size_usdc` would exceed `RISK_MAX_CATEGORY_EXPOSURE`.

Category exposure is computed from `PortfolioState.category_exposure(category, prices)`, which filters positions by their recorded `category` field.

This prevents over-concentration in a single event category (e.g., "politics" or "crypto").

---

### 8. Daily Loss

**Config:** `RISK_MAX_DAILY_LOSS` (default: $100)

Rejects all trades if `portfolio.daily_loss >= RISK_MAX_DAILY_LOSS`.

`daily_loss` accumulates from `PaperBroker` on every losing SELL fill. It resets at midnight (implicitly — the broker tracks loss by calendar date).

---

### 9. Open Positions

**Config:** `RISK_MAX_OPEN_POSITIONS` (default: 20)

Rejects if `portfolio.open_position_count() >= RISK_MAX_OPEN_POSITIONS`.

`open_position_count()` counts positions where `size_tokens > 0`.

---

### 10. Open Orders

**Config:** `RISK_MAX_OPEN_ORDERS` (default: 40)

Rejects if `open_order_count >= RISK_MAX_OPEN_ORDERS`.

`open_order_count` is passed into `evaluate()` from the orchestrator, which fetches it from `broker.open_order_count()`.

---

## Cooldown Mechanics

```
record_loss("cond1")
  → loss_streak["cond1"] += 1
  → consecutive_global_losses += 1
  → if streak >= COOLDOWN_AFTER_LOSSES:
       cooldown_until["cond1"] = now + COOLDOWN_DURATION_SECONDS
  → if global_losses >= COOLDOWN_AFTER_LOSSES × 2:
       global_cooldown_until = now + COOLDOWN_DURATION_SECONDS × 2
       consecutive_global_losses = 0

record_win("cond1")
  → loss_streak["cond1"] = 0
  → consecutive_global_losses = max(0, consecutive_global_losses - 1)
```

---

## RiskDecision Model

```python
class RiskDecision:
    condition_id: str
    token_id: str
    verdict: RiskVerdictType   # APPROVED | REJECTED
    reasons: list[str]         # populated only on REJECTED
    decided_at: datetime
```

Every rejected trade logs all failing reasons via `logger.info`.

---

## Tuning Recommendations

| Scenario | Adjustment |
|----------|-----------|
| Too many trades being placed | Lower `RISK_MAX_OPEN_POSITIONS` or `SCAN_MIN_EDGE_BPS` |
| Running out of capital quickly | Lower `RISK_MAX_NOTIONAL_PER_MARKET` |
| Too concentrated in one event type | Lower `RISK_MAX_CATEGORY_EXPOSURE` |
| Stale forecasts being executed | Lower `RISK_SIGNAL_STALENESS_SECONDS` |
| Trading too close to resolution | Increase `RISK_EXPIRY_NO_TRADE_HOURS` |
| Recovering too slowly after losses | Lower `RISK_COOLDOWN_DURATION_SECONDS` |
| Too aggressive after a bad run | Increase `RISK_COOLDOWN_AFTER_LOSSES` |
