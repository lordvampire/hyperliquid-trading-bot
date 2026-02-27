# 🚀 DEPLOYMENT.md — Live Trading Runbook

**Hyperliquid Trading Bot — Phase 4 Production Guide**

---

## Overview

Phase 4 adds production-grade safety guards, audit logging, and live trading
orchestration. Every trade passes through `SafetyManager` before execution.

```
Signal → check_pre_trade() → PositionSizer → Exchange → log_trade()
```

---

## Pre-flight Checklist

Before going live, verify:

- [ ] `config/base.yaml` has correct `telegram.admin_user_ids`
- [ ] `.env` has valid `HL_SECRET_KEY`, `HL_WALLET_ADDRESS`, `TELEGRAM_BOT_TOKEN`
- [ ] `HL_TESTNET=false` for mainnet (default is testnet)
- [ ] `deployment.starting_capital` set to your intended amount
- [ ] Run full test suite: `python -m pytest tests/ -v`
- [ ] Paper trade first: `/paper_trade BTC 14`
- [ ] Optimize params: `/optimize BTC 30`

---

## Safety Configuration (`config/base.yaml`)

```yaml
safety:
  max_daily_dd_pct: 5.0          # Circuit breaker: stop if daily loss ≥ 5%
  max_leverage: 35               # Hard stop if leverage > 35x; warn at 30x
  max_slippage_pct: 2.0          # Reject trade if estimated slippage > 2%
  network_latency_limit_ms: 2000 # Reject if API latency > 2 seconds
  audit_log_path: "logs/audit.log"

deployment:
  strategy: "strategy_b"
  mode: "backtest"               # Change to "live" for mainnet
  starting_capital: 1000.0
  email_reports: true
  report_time_utc: "18:00"       # Daily report at 7 PM Berlin

telegram:
  admin_user_ids: [5890731372]   # Faruk's Telegram ID
```

---

## Telegram Commands (Phase 4)

### `/optimize [symbol] [days]`
Runs sensitivity analysis + grid search. Saves best params to `param_history.json`.

```
/optimize BTC 30
/optimize ETH 14
```

### `/paper_trade [symbol] [days]`
Simulates live trading on recent data. Reports P&L and detects model drift.

```
/paper_trade BTC 14
/paper_trade SOL 7
```

### `/go_live [symbol] [amount]`
🔴 **ADMIN ONLY** — Starts live trading.

```
/go_live BTC 500
```

- Checks your Telegram `user_id` against `admin_user_ids` in config
- Writes audit trail entry for the go-live event
- All subsequent signals go through SafetyManager before execution

---

## Circuit Breaker

The circuit breaker automatically halts trading when:

| Condition | Limit | Action |
|-----------|-------|--------|
| Daily loss | ≥ 5% of starting balance | Block all new trades |
| Leverage | > 35x | Reject signal |
| Slippage est. | > 2% | Reject signal |
| API latency | > 2 seconds | Reject signal |
| Signal strength | < 0.2 | Reject (insufficient liquidity signal) |

**To reset the circuit breaker:**  
Wait for daily reset (00:00 UTC) or restart the bot.

---

## Audit Log

Every trade action is written to `logs/audit.log` (append-only, JSONL format).

```
{"timestamp": "...", "trade_id": "T-...", "symbol": "BTC", "direction": "LONG",
 "entry_price": 45000, "size": 0.001, "status": "executed", "pnl": 0.0, ...}
```

**Archived daily** at `logs/audit_YYYY-MM-DD.log`  
**Daily report** at `logs/report_YYYY-MM-DD.html`

---

## Step-by-Step: Going Live

### 1. Configure environment

```bash
cd ~/hyperliquid-trading-bot
cp example.env .env
nano .env
# Set: HL_SECRET_KEY, HL_WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, HL_TESTNET=false
```

### 2. Run final tests

```bash
source venv/bin/activate
python -m pytest tests/ -v
```

### 3. Verify safety manager

```bash
python -c "
from safety_manager import SafetyManager
from config.manager import ConfigManager
config = ConfigManager('config/base.yaml', 'live')
safety = SafetyManager(config)
print(f'✅ SafetyManager ready')
print(f'   Max daily DD: {safety.max_daily_dd_pct}%')
print(f'   Max leverage: {safety.max_leverage}x')
print(f'   Network healthy: {safety.check_network_health()}')
"
```

### 4. Paper trade first (≥ 2 weeks recommended)

```
Telegram → /paper_trade BTC 14
```

Review results. If divergence alerts appear → re-optimize before going live.

### 5. Optimize parameters

```
Telegram → /optimize BTC 30
```

### 6. Go live with small capital

```
Telegram → /go_live BTC 100
```

Start with $100–500 to verify the pipeline before scaling up.

### 7. Monitor

```
Telegram → /status    (shows safety check summary)
Telegram → /risk      (shows circuit breaker status)
```

---

## Emergency Procedures

### Stop trading immediately

```bash
# Kill the bot process
pkill -f "python bot.py"
```

Or via Telegram:
```
/shutdown
```

### Close all positions manually

Log in to [app.hyperliquid.xyz](https://app.hyperliquid.xyz) and close positions manually.
The bot currently does **not** auto-close on shutdown — always verify open positions.

### Review audit log

```bash
tail -f logs/audit.log | python -m json.tool
```

---

## Daily Operations

| Time (UTC) | Action |
|------------|--------|
| 00:00 | Daily reset — P&L counter resets, logs archived |
| 18:00 | Daily report generated (`logs/report_YYYY-MM-DD.html`) |
| Continuous | Circuit breaker monitors every signal |

---

## Rollback Procedure

If anything goes wrong:

1. `pkill -f "python bot.py"` — stop the bot
2. Close all open positions on Hyperliquid web UI
3. Review `logs/audit.log` to understand what happened
4. Fix the bug
5. Run `python -m pytest tests/ -v` — all must pass
6. Restart with `/go_live [symbol] [small_amount]`

---

## Architecture

```
bot.py
  ├── /optimize  → OptimizationRunner (sensitivity + grid + Optuna)
  ├── /paper_trade → PaperTrader (simulate on real data)
  └── /go_live   → LiveDeployment
                        ├── SafetyManager (circuit breaker + audit)
                        ├── PositionSizer (dynamic sizing)
                        ├── HyperliquidExchange (order placement)
                        └── ParameterRegistry (run tracking)
```

---

## Configuration Reference

| Key | Default | Description |
|-----|---------|-------------|
| `safety.max_daily_dd_pct` | 5.0 | Max daily loss % before circuit breaker |
| `safety.max_leverage` | 35 | Hard leverage cap |
| `safety.max_slippage_pct` | 2.0 | Max acceptable slippage |
| `safety.network_latency_limit_ms` | 2000 | Max API latency (ms) |
| `deployment.starting_capital` | 1000.0 | Initial capital (USD) |
| `deployment.mode` | backtest | Trading mode |
| `telegram.admin_user_ids` | [5890731372] | Telegram IDs allowed to /go_live |

---

_Phase 4 complete. Production-ready with safety guards. Start small, verify, scale._
