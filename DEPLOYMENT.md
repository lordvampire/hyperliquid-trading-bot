# 🚀 DEPLOYMENT.md — Live Trading Runbook

**Hyperliquid Trading Bot — VMR Strategy, Production Guide**

---

## Overview

The VMR (Volatility Mean Reversion) bot detects hourly price spikes and enters mean-reversion trades. Production flow:

```
Signal detected → VMRStrategy.analyze() → LiveTrader.place_order() → Hyperliquid API
```

All safety guards (position limits, daily loss cap, max hold time) are enforced in `strategy_engine.py` and `vmr_trading_bot.py`.

---

## Pre-flight Checklist

Before going live, verify:

- [ ] `.env` has valid `HL_SECRET_KEY`, `HL_WALLET_ADDRESS`
- [ ] `HL_TESTNET=true` for testnet, `HL_TESTNET=false` for mainnet
- [ ] `HL_DRY_RUN=false` (set `true` first to confirm orders validate)
- [ ] `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` set and tested
- [ ] Run test suite: `pytest tests/ -v`
- [ ] Run optimizer: `/optimize BTC ETH SOL`
- [ ] Validate results: `/backtest BTC 30`
- [ ] Review params: `/show_best_params`

---

## Environment Variables (`.env`)

```env
# Hyperliquid credentials
HL_SECRET_KEY=0x...                  # Private key (required for LIVE mode)
HL_WALLET_ADDRESS=0x...             # Wallet address
HL_TESTNET=true                     # true = testnet, false = mainnet
HL_DRY_RUN=false                    # true = pre-flight only, no orders sent

# Telegram
TELEGRAM_BOT_TOKEN=123456:ABC-DEF...
TELEGRAM_CHAT_ID=5890731372

# Paper trading (used when HL_SECRET_KEY is NOT set)
PAPER_BALANCE=10000.0
```

> **Mode Detection:**
> - `HL_SECRET_KEY` present → **LIVE mode** (real orders)
> - `HL_SECRET_KEY` absent  → **PAPER mode** (simulation)
> - `HL_DRY_RUN=true`       → **DRY RUN** (validates, no orders)

---

## VMR Strategy Configuration

All parameters live in `VMRConfig` inside `strategy_engine.py`. Change them once — backtest, paper, and live modes all pick up the change.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `spike_threshold_pct` | 1.0 | 1h return (%) to trigger spike |
| `bb_std_multiplier` | 2.0 | Bollinger Band width multiplier |
| `sl_pct` | 0.005 | Stop-loss fraction (0.005 = 0.5%) |
| `tp_pct` | 0.015 | Take-profit fraction (0.015 = 1.5%) |
| `position_size_pct` | 0.01 | Fraction of account per trade (1%) |
| `max_hold_hours` | 24 | Max hours to hold position |
| `daily_loss_limit_pct` | 0.05 | Max daily loss (5%) |
| `max_open_positions` | 3 | Max concurrent positions |
| `scan_interval_seconds` | 900 | Scan every 15 minutes |
| `symbols` | BTC, ETH, SOL | Instruments to trade |

To update params live (without restart):
```
/set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
```

---

## Telegram Commands (Production)

### `/start_auto`
Launches the autonomous trading loop. Scans all configured symbols every 15 minutes.

### `/stop_auto`
Stops the loop. Existing positions remain open — you must close them manually or wait for SL/TP.

### `/stop_all`
Stops loop **and** closes all open positions at market price (emergency stop).

### `/status`
Shows current open positions, unrealized P&L, account balance, loop info.

### `/optimize [BTC|ETH|SOL]`
Runs parameter grid search (~10,000 combinations) for the given symbol.

```
/optimize BTC
/optimize BTC ETH SOL
```

Results saved to `optimization_results/` and top-3 to `best_params.json`.

### `/show_best_params`
Displays top-3 parameter sets from the last optimization run.

### `/backtest [symbol] [days]`
Backtests the current (or optimized) params on real historical data.

```
/backtest BTC 30
/backtest BTC 30 --use-optimized-params
```

### `/set_params spike=X bb_mult=Y sl=Z tp=W size=V hold=H`
Updates VMR parameters live (takes effect immediately, without restart).

### `/balance`
Shows account balance and risk limits.

### `/mode`
Shows current trading mode: LIVE / PAPER / DRY-RUN.

---

## Risk Guards

| Condition | Limit | Behaviour |
|-----------|-------|-----------|
| Daily P&L loss | ≥ 5% of balance | Bot stops opening new positions |
| Open positions | ≥ 3 | New signals are skipped |
| Position hold time | ≥ 24h | Forced exit at market |
| Stop-loss hit | 0.5% below entry | Position closed immediately |
| Take-profit hit | 1.5% above entry | Position closed, profit realised |

---

## Audit Logging

Every trade attempt is logged to `vmr_bot.log` (append-only):

```
2026-03-01 12:30:00 - [INFO] - ✅ LONG BTC — entry $64,400 | SL $64,080 | TP $65,360
2026-03-01 14:15:00 - [INFO] - 🎯 TP hit BTC — closed @ $65,360 | P&L +$153.60
```

---

## Step-by-Step: Going Live

### 1. Set up environment

```bash
cd ~/hyperliquid-trading-bot
cp example.env .env
nano .env
# Set: HL_SECRET_KEY, HL_WALLET_ADDRESS, TELEGRAM_BOT_TOKEN, HL_TESTNET=true
```

### 2. Run final tests

```bash
source venv/bin/activate
pytest tests/ -v
```

### 3. Dry-run validation

```bash
# Set HL_DRY_RUN=true in .env first
python vmr_trading_bot.py
# In Telegram: /start_auto
# Watch logs — orders should show DRY-RUN label
```

### 4. Optimize parameters

```
Telegram → /optimize BTC ETH SOL
# Wait 5–15 min for results
Telegram → /show_best_params
Telegram → /backtest BTC 30
```

### 5. Go live with small capital

```
# Set HL_DRY_RUN=false in .env
# Restart: python vmr_trading_bot.py
Telegram → /set_params spike=1.0 bb_mult=2.0 sl=0.005 tp=0.015 size=0.01 hold=24
Telegram → /start_auto
```

Start with 1% position size and low capital. Monitor via `/status`.

### 6. Monitor

```
/status    → open positions, P&L, loop health
/stats     → completed trade statistics
/balance   → account balance, daily loss
```

---

## Emergency Procedures

### Stop trading immediately

```
Telegram → /stop_all
```

Or kill the process:

```bash
pkill -f "python vmr_trading_bot.py"
```

### Close positions manually

Log in to [app.hyperliquid.xyz](https://app.hyperliquid.xyz) and close positions from the UI.

### Review logs

```bash
tail -100 vmr_bot.log
```

---

## Daily Operations

| Action | When |
|--------|------|
| Check `/status` | Morning and evening |
| Review `vmr_bot.log` | If any alerts |
| Re-optimize | Weekly or after market regime change |
| Update params with `/set_params` | After reviewing optimization results |

---

## Rollback Procedure

1. `/stop_all` — stop bot and close all positions
2. Review `vmr_bot.log` to understand what happened
3. Fix the bug or parameter issue
4. `pytest tests/ -v` — confirm all pass
5. `/optimize BTC` — refresh parameters
6. Restart with small position size: `/set_params size=0.005`
7. `/start_auto` — resume

---

## Architecture Reference

```
vmr_trading_bot.py
  ├── /start_auto     → Autonomous loop (15-min scans)
  ├── /stop_auto      → Pause loop
  ├── /stop_all       → Emergency: pause + close all
  ├── /optimize       → Spawns optimizer.py subprocess
  ├── /backtest       → Runs VMRStrategy.run_backtest()
  ├── /set_params     → Updates VMRConfig live
  └── /status, /stats, /balance, /mode, /signals, /analyze

strategy_engine.py   ← VMRConfig + VMRStrategy (single source of truth)
live_trader.py       ← Hyperliquid SDK: market_open, market_close, orders
optimizer.py         ← Grid search over 10,000+ param combinations
```

---

_VMR strategy, production-ready. Start small, verify, scale._
