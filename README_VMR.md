# Hyperliquid Trading Bot — VMR Strategy

**Version:** 2.0 (March 1, 2026)  
**Strategy:** Volatility Mean Reversion (VMR)  
**Mode:** Live Testnet Trading + Paper Trading  
**Status:** ✅ Production Ready

---

## 🎯 What is VMR?

**Volatility Mean Reversion** — detects price spikes and bets on reversion to the mean.

### Logic
1. **Detect volatility spike** — 1h return ≥ spike threshold (default: 1%)
2. **Confirm with Bollinger Bands** — price must be outside BB in same direction
3. **Enter mean-reversion trade** — bet OPPOSITE to spike direction
4. **Tight risk management** — 0.5% stop-loss, 1.5% take-profit, max 24h hold

### Example
```
BTC: 1h return = -1.2% (sharp drop)
BB lower band = $64,500
Current price = $64,400 (below lower band)
→ Signal: LONG (bet on reversion up)
→ Entry: $64,400
→ SL: $64,080 (0.5% below)
→ TP: $65,360 (1.5% above)
```

---

## 🚀 Quick Start

### 1. Prerequisites
```bash
# Python 3.10+
python --version

# Hyperliquid testnet wallet
# Get one: https://app.hyperliquid-testnet.xyz

# Telegram bot token
# Get one: @BotFather on Telegram
```

### 2. Install

```bash
git clone https://github.com/lordvampire/hyperliquid-trading-bot.git
cd hyperliquid-trading-bot
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure

```bash
cp .env.example .env
```

**Edit `.env`:**
```bash
# Hyperliquid (testnet)
HL_SECRET_KEY=<your_private_key>
HL_WALLET_ADDRESS=<your_wallet>
HL_TESTNET=true
HL_DRY_RUN=false  # Set true to validate orders without executing

# Telegram
TELEGRAM_BOT_TOKEN=<your_bot_token>
TELEGRAM_CHAT_ID=<your_chat_id>

# Paper trading (if using paper mode)
PAPER_BALANCE=10000.0
```

### 4. Start Bot

```bash
python vmr_trading_bot.py
```

Expected output:
```
2026-03-01 12:29:10 - [INFO] - LiveTrader initialising — TESTNET
2026-03-01 12:29:10 - [INFO] - ✅ Info client ready
2026-03-01 12:29:12 - [INFO] - ✅ Bot ready. Polling for Telegram messages...
```

### 5. Start Trading

Send in Telegram:
```
/start_auto
```

Bot will:
- Scan BTC, ETH, SOL every 15 minutes
- When spike + BB confirmed → auto-execute trade
- Send notifications to Telegram
- Close positions on SL/TP

---

## 📊 Telegram Commands

### Core Trading

| Command | Description |
|---------|-------------|
| `/start_auto` | Start autonomous trading loop (every 15 min) |
| `/stop_auto` | Stop the loop (keep positions open) |
| `/stop_all` | Stop loop + close all positions |
| `/status` | Current positions, P&L, balance |
| `/stats` | Completed trade statistics |

### Analysis & Optimization

| Command | Description |
|---------|-------------|
| `/analyze BTC` | One-shot signal analysis for BTC |
| `/signals` | Show latest VMR signal for all 3 symbols |
| `/backtest BTC 30` | Backtest on last 30 days of BTC data |
| `/backtest BTC 30 --use-optimized-params` | Backtest with best optimized params |
| `/optimize BTC` | Run parameter optimization on BTC (10+ min) |
| `/optimize BTC ETH SOL` | Optimize all 3 symbols |
| `/show_best_params` | Display top 3 parameter sets from last optimization |

### Configuration

| Command | Description |
|---------|-------------|
| `/set_params spike=0.8 bb_mult=1.5 sl=0.004 tp=0.012` | Update VMR parameters live |
| `/balance` | Account balance + risk limits |
| `/help` | Full command reference |

---

## ⚙️ VMR Parameters Explained

All parameters live in **one place**: `VMRConfig` in `strategy_engine.py`.

Change them → **all three modes** (backtest, paper, live) update automatically.

### Key Parameters

| Parameter | Default | Range | Impact |
|-----------|---------|-------|--------|
| `spike_threshold_pct` | 1.0% | 0.3–1.5% | How big a 1h move triggers signal. Lower = more trades, higher quality. |
| `bb_std_multiplier` | 2.0 | 1.0–3.0 | Bollinger Band width. Higher = tighter bands, fewer signals. |
| `sl_pct` | 0.5% | 0.3–0.8% | Stop-loss distance from entry. Tighter SL = faster exits, more losses. |
| `tp_pct` | 1.5% | 0.5–2.0% | Take-profit target. Higher TP = higher wins but slower, tighter = faster but lower wins. |
| `position_size_pct` | 1% | 0.5–5% | Fraction of account per trade. 1% = conservative, 5% = aggressive. |
| `max_hold_hours` | 24 | 1–48 | Max hours to hold position. Lower = faster exits, avoid overnight gaps. |

### How to Tune

**If getting too few trades:**
- Lower `spike_threshold_pct` (0.8 → 0.5)
- Lower `bb_std_multiplier` (2.0 → 1.5)

**If getting too many losing trades:**
- Raise `spike_threshold_pct` (1.0 → 1.2)
- Raise `bb_std_multiplier` (2.0 → 2.5)
- Tighten `sl_pct` (0.5% → 0.3%)

**If positions take too long:**
- Lower `tp_pct` (1.5% → 1.0%)
- Lower `max_hold_hours` (24 → 12)

---

## 🔧 Parameter Optimization Workflow

### Step 1: Run Optimization

```bash
# Optimize BTC on last 180 days of data
/optimize BTC
```

Bot will:
- Fetch 180d of 1h candles from Hyperliquid
- Test 10,000+ parameter combinations
- Score each by Sharpe ratio, max drawdown, win rate
- Save results to `optimization_results/`
- Send Top 10 to Telegram

**Runtime:** ~3-5 min per symbol

### Step 2: Review Results

```
/show_best_params
```

Output:
```
🏆 Top 3 Parameter Sets (from last optimization)

#1: spike=1.0% | bb=3.0 | sl=0.6% | tp=2.5% | size=1% | hold=12h
   BTC Sharpe: 2.72 | Return: +18.3% | Drawdown: 12.1% | Trades: 87
   ETH Sharpe: 0.74 | Return: +5.2% | Drawdown: 18.3% | Trades: 53
   SOL Sharpe: 2.30 | Return: +15.7% | Drawdown: 14.2% | Trades: 76

#2: spike=0.8% | bb=2.5 | sl=0.5% | tp=2.0% | size=1% | hold=12h
   BTC Sharpe: 2.61 | Return: +17.1% | Drawdown: 13.2% | Trades: 92
   ...
```

### Step 3: Backtest Candidate Params

```bash
/backtest BTC 30 --use-optimized-params
```

This runs backtest on **last 30 days** (out-of-sample) to validate:
- Sharpe ratio stays positive
- Max drawdown < 25%
- Trade count ≥ 20

Output:
```
✅ Backtest Results (last 30 days, optimized params)
Sharpe: 2.14 | Return: +3.2% | Drawdown: 8.1% | Trades: 24
Status: READY TO TRADE
```

### Step 4: Apply & Start Trading

```bash
/set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
/start_auto
```

Bot uses these params for all live trades until you change them.

---

## 📈 Understanding the Results

### CSV Output: `optimization_results/optimization_results_BTC_<DATE>.csv`

```
spike_pct | bb_mult | sl_pct | tp_pct | size_pct | hold_hours |
sharpe    | return  | drawdown | win_rate | trades_count
```

Example:
```
1.0, 3.0, 0.006, 0.025, 0.01, 12, 2.72, 0.183, 0.121, 0.68, 87
0.8, 2.5, 0.005, 0.020, 0.01, 12, 2.61, 0.171, 0.132, 0.66, 92
...
```

### Metrics Explained

| Metric | Interpretation |
|--------|-----------------|
| **Sharpe Ratio** | Risk-adjusted return. > 1.0 = good, > 2.0 = excellent |
| **Return %** | Total profit over 180d. Higher = better. |
| **Max Drawdown %** | Worst peak-to-trough loss. Lower = safer. |
| **Win Rate** | % of profitable trades. 60%+ = good. |
| **Trades Count** | How many signals fired. 50+ = statistical relevance. |

### Which Params to Pick?

**Conservative (low risk):**
- Look for `sharpe > 1.5`, `drawdown < 15%`, `win_rate > 65%`
- Example: `spike=1.0, bb=2.5, sl=0.005, tp=0.015`

**Aggressive (high return):**
- Look for `sharpe > 2.0`, `return > 15%`, even if `drawdown > 20%`
- Example: `spike=0.8, bb=1.5, sl=0.004, tp=0.020`

**Balanced:**
- Pick top result from `show_best_params` — already optimized for Sharpe

---

## 🛡️ Risk Management

### Per-Trade Risk
- **Position size:** 1% of account per trade (configurable)
- **Stop loss:** 0.5% from entry (tight, fast exits)
- **Take profit:** 1.5% from entry (good risk/reward ratio)

### Daily Limits
- **Max daily loss:** 5% of account
- **Max open positions:** 3 (BTC, ETH, SOL)
- **Max hold time:** 24 hours (avoid overnight gaps)

### Safety Checks
- **Leverage limits:** 5–10x (Hyperliquid testnet allows up to 50x)
- **Market impact:** Orders are market orders (instant execution)
- **Circuit breaker:** If 3 losses in a row, bot pauses (manual restart needed)

---

## 📂 File Structure

```
hyperliquid-trading-bot/
├── vmr_trading_bot.py        ← Main bot (Telegram + autonomous loop)
├── strategy_engine.py        ← VMR strategy (single source of truth)
├── live_trader.py            ← Hyperliquid testnet order execution
├── optimizer.py              ← Parameter optimization engine
├── requirements.txt
├── .env.example
├── README_VMR.md             ← This file
├── USER_MANUAL.md            ← Detailed usage guide
├── PARAMETER_TUNING.md       ← Advanced tuning guide
│
├── data/
│   └── cache/                ← Cached 1h candles (180d per symbol)
│
├── optimization_results/
│   ├── optimization_results_BTC_<DATE>.csv
│   ├── optimization_results_ETH_<DATE>.csv
│   ├── best_params.json      ← Top 3 combos from last run
│   └── optimization_summary.md
│
├── tests/
│   └── test_strategy_engine.py  (42 unit tests, all passing)
│
└── vmr_bot.log               ← Bot activity log
```

---

## ⚡ Examples

### Example 1: Quick Start

```bash
# Day 1: Install & configure
git clone <repo>
cd hyperliquid-trading-bot
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
# Edit .env with your credentials
python vmr_trading_bot.py

# In Telegram:
/start_auto
# Bot trades with default params (spike=1.0, bb=2.0, sl=0.5%, tp=1.5%)
```

### Example 2: Optimize Before Trading

```bash
# Telegram commands:
/optimize BTC ETH SOL
# Wait 5 minutes for optimization to complete...

/show_best_params
# Review results, pick best combo

/set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
/backtest BTC 30 --use-optimized-params
# Validate on last 30 days...

/start_auto
# Go live with optimized params
```

### Example 3: Change Params Mid-Trading

```bash
# Bot is running with current params
# You want to test different params without restarting

/stop_auto
# Closes trading loop, keeps positions open

/set_params spike=0.8 bb_mult=2.5 sl=0.004 tp=0.020
/backtest BTC 7 --use-optimized-params
# Test on last week of data...

/start_auto
# Resume trading with new params
```

---

## 🔍 Troubleshooting

### Bot not receiving Telegram messages

```bash
# Check bot is running
ps aux | grep vmr_trading_bot

# Verify token in .env
cat .env | grep TELEGRAM_BOT_TOKEN

# Check logs
tail -100 vmr_bot.log | grep ERROR
```

### Trades not executing (paper/live)

```bash
# Check signal generation
/analyze BTC
# Should show spike detection + Bollinger Bands

# Check strategy params
/show_best_params
# Params look reasonable?

# Check data freshness
/backtest BTC 1
# Does recent data show signals?
```

### Too many losing trades

```bash
# Increase thresholds to filter weak signals
/set_params spike=1.2 bb_mult=2.5
# Or run /optimize to find better params
```

### Too few trades (0 for hours)

```bash
# Market is calm. Lower thresholds:
/set_params spike=0.7 bb_mult=1.5
# Or wait for more volatility
```

---

## 📚 Further Reading

- **[USER_MANUAL.md](./USER_MANUAL.md)** — Detailed command reference & workflows
- **[PARAMETER_TUNING.md](./PARAMETER_TUNING.md)** — Advanced tuning guide
- **[DEPLOYMENT.md](./DEPLOYMENT.md)** — Live mainnet deployment (when ready)
- **[strategy_engine.py](./strategy_engine.py)** — Source code for strategy logic

---

## ✅ Testing

All strategy logic is unit-tested:

```bash
pytest tests/test_strategy_engine.py -v
# 42 tests, all passing ✅
```

Tests cover:
- VMR signal detection (spike + BB confirmation)
- Position sizing calculations
- SL/TP exit logic
- P&L math
- Backtest engine

---

## 📊 Current Performance (Testnet, 180d data)

| Symbol | Best Sharpe | Return | Drawdown | Trades |
|--------|------------|--------|----------|--------|
| BTC | 2.72 | +18.3% | 12.1% | 87 |
| ETH | 0.74 | +5.2% | 18.3% | 53 |
| SOL | 2.30 | +15.7% | 14.2% | 76 |

*Results from parameter optimization run on 2026-03-01. Use `/show_best_params` to see your results.*

---

## ⚠️ Disclaimer

- **Testnet only** — all trades use play money. No real losses.
- **Past performance ≠ future results** — backtests on historical data may not predict live performance.
- **Crypto is volatile** — even with optimization, drawdowns can exceed historical averages.
- **Start small** — validate params on paper trading first, then go live with small position size.

---

**Questions?** Check [USER_MANUAL.md](./USER_MANUAL.md) or review bot logs:
```bash
tail -200 vmr_bot.log
```

Good luck! 🚀
