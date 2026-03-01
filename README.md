# Hyperliquid Trading Bot — VMR Strategy

A Python-based autonomous trading bot for [Hyperliquid](https://hyperliquid.xyz) using a **Volatility Mean Reversion (VMR)** strategy, with Telegram integration, parameter optimization, and paper/live trading modes.

**Status:** ✅ Production Ready (VMR Strategy v2.0, March 2026)

---

## Quick Start

### 1. Prerequisites
- Python 3.10+
- A Hyperliquid testnet wallet ([get one here](https://app.hyperliquid-testnet.xyz))
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

### 2. Setup

```bash
git clone https://github.com/lordvampire/hyperliquid-trading-bot.git
cd hyperliquid-trading-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp example.env .env
# Edit .env with your keys
```

| Variable | Description |
|---|---|
| `HL_SECRET_KEY` | Your Hyperliquid private key (for live/testnet trading) |
| `HL_WALLET_ADDRESS` | Your wallet address |
| `HL_TESTNET` | `true` for testnet, `false` for mainnet |
| `HL_DRY_RUN` | `true` to validate orders without executing |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |
| `PAPER_BALANCE` | Starting balance for paper trading (default: `10000.0`) |

> **Mode Detection:**
> - `HL_SECRET_KEY` set → **LIVE mode** (real orders on testnet/mainnet)
> - `HL_SECRET_KEY` missing → **PAPER mode** (simulation, no real money)
> - `HL_DRY_RUN=true` → **DRY RUN** (validates but sends no orders)

### 4. Run

```bash
python vmr_trading_bot.py
```

### 5. Start Trading

In Telegram, send:
```
/start_auto
```

---

## 🎯 VMR Strategy

**Volatility Mean Reversion** — detects price spikes and bets on reversion to the mean.

### Logic

1. **Detect volatility spike** — 1h return ≥ spike threshold (default: 1%)
2. **Confirm with Bollinger Bands** — price must be outside BB in same direction
3. **Enter mean-reversion trade** — bet OPPOSITE to spike direction
4. **Tight risk management** — 0.5% stop-loss, 1.5% take-profit, max 24h hold

### Example

```
BTC: 1h return = -1.2% (sharp drop)
BB lower band = $64,500, Current price = $64,400 (below lower band)
→ Signal: LONG (bet on reversion up)
→ Entry: $64,400 | SL: $64,080 (-0.5%) | TP: $65,360 (+1.5%)
```

---

## 📊 Telegram Commands

### Core Trading

| Command | Description |
|---------|-------------|
| `/start` | Welcome message and quick status |
| `/help` | Full command reference |
| `/start_auto` | Start autonomous trading loop (every 15 min) |
| `/stop_auto` | Stop the loop (keep positions open) |
| `/stop_all` | Stop loop + close all positions at market |
| `/status` | Current positions, P&L, loop info |
| `/stats` | Completed trade statistics |
| `/balance` | Account balance + risk settings |
| `/mode` | Show current trading mode (live/paper/dry-run) |

### Analysis

| Command | Description |
|---------|-------------|
| `/analyze [BTC\|ETH\|SOL]` | On-demand signal analysis for one symbol |
| `/signals` | Latest VMR signal for all symbols |
| `/backtest [BTC] [days]` | Run backtest on real historical data |

### Optimization

| Command | Description |
|---------|-------------|
| `/optimize [BTC\|ETH\|SOL]` | Run parameter grid search (10,000+ combinations) |
| `/show_best_params` | Display top 3 parameter sets from last optimization |
| `/set_params spike=X bb_mult=Y sl=0.005 tp=0.015 size=0.01 hold=24` | Update VMR parameters live |

---

## ⚙️ VMR Parameters

All parameters live in **one place**: `VMRConfig` in `strategy_engine.py`. All modes (backtest, paper, live) pick up changes automatically.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `spike_threshold_pct` | 1.0% | 1h return magnitude to trigger signal |
| `bb_std_multiplier` | 2.0 | Bollinger Band width multiplier |
| `sl_pct` | 0.5% | Stop-loss distance from entry |
| `tp_pct` | 1.5% | Take-profit distance from entry |
| `position_size_pct` | 1% | Fraction of account per trade |
| `max_hold_hours` | 24 | Max hours to hold a position |
| `scan_interval_seconds` | 900 | How often the loop scans (15 min) |
| `symbols` | BTC, ETH, SOL | Instruments traded |

---

## 🔧 Parameter Optimization Workflow

```bash
# Step 1: Run optimization (5–15 min)
/optimize BTC

# Step 2: Review results
/show_best_params

# Step 3: Backtest on out-of-sample data
/backtest BTC 30

# Step 4: Apply and start trading
/set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
/start_auto
```

Or run the optimizer as a standalone CLI:

```bash
python optimizer.py                  # BTC, ETH, SOL (all)
python optimizer.py --symbol BTC     # Single symbol
python optimizer.py --dry-run        # Quick smoke test
```

Results saved to `optimization_results/` and `best_params.json`.

---

## 🛡️ Risk Management

| Guard | Value |
|-------|-------|
| Daily loss limit | 5% of account |
| Max open positions | 3 |
| Stop-loss (default) | 0.5% from entry |
| Take-profit (default) | 1.5% from entry |
| Max hold time | 24 hours |
| Leverage | 5–10x (configurable) |

---

## Project Structure

```
hyperliquid-trading-bot/
├── vmr_trading_bot.py     ← Main bot (Telegram + autonomous loop)
├── strategy_engine.py     ← VMR strategy (single source of truth)
├── live_trader.py         ← Hyperliquid order execution (testnet/mainnet)
├── optimizer.py           ← Parameter grid-search optimizer
├── requirements.txt
├── example.env
│
├── optimization_results/  ← CSV results per symbol + best_params.json
├── candle_cache/          ← Cached 180d 1h candles per symbol
├── tests/
│   └── test_strategy_engine.py  (42 unit tests)
│
├── README.md              ← This file
├── README_VMR.md          ← Detailed VMR guide
└── USER_MANUAL.md         ← Full usage manual
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│         Hyperliquid API (mainnet)       │
│   OHLCV candles (read-only, no key)     │
└─────────────┬───────────────────────────┘
              │
   ┌──────────▼──────────┐
   │  strategy_engine.py │  ← VMR logic (spike + BB detection)
   │  (VMRConfig, VMR-   │
   │  Strategy, VMRSig.) │
   └──────────┬──────────┘
              │ signals
   ┌──────────▼──────────────────────────┐
   │      vmr_trading_bot.py             │
   │  • Telegram command handler         │
   │  • Autonomous scan loop             │
   │  • Paper / Live state management    │
   └──────────┬──────────────────────────┘
              │ orders (LIVE mode only)
   ┌──────────▼──────────┐
   │    live_trader.py   │  ← Market orders, SL/TP triggers
   │ (Hyperliquid SDK)   │
   └─────────────────────┘

   ┌─────────────────────┐
   │    optimizer.py     │  ← Standalone grid-search (10k+ combos)
   │  (CLI / Telegram)   │
   └─────────────────────┘
```

---

## Testing

```bash
pytest tests/test_strategy_engine.py -v
# 42 tests, all passing ✅
```

---

## Current Performance (Testnet, 180d data)

| Symbol | Best Sharpe | Return | Drawdown | Trades |
|--------|------------|--------|----------|--------|
| BTC | 2.72 | +18.3% | 12.1% | 87 |
| ETH | 0.74 | +5.2% | 18.3% | 53 |
| SOL | 2.30 | +15.7% | 14.2% | 76 |

*From parameter optimization run on 2026-03-01. Run `/show_best_params` to see your own results.*

---

## Further Reading

- **[README_VMR.md](./README_VMR.md)** — Detailed VMR strategy guide
- **[USER_MANUAL.md](./USER_MANUAL.md)** — Full usage manual
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** — Live mainnet deployment guide
- **[SETUP_GUIDE.md](./SETUP_GUIDE.md)** — Step-by-step setup instructions

---

## License

Private — not for distribution.
