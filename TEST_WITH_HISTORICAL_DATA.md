# Testing with Historical Data — VMR Strategy
## Quick Reference Guide

---

## 📊 TEST SCENARIO: Optimize VMR on Historical Data

The VMR optimizer fetches real 1h OHLCV candles from Hyperliquid and tests ~10,000 parameter combinations to find the best settings.

---

### Option A: FULL OPTIMIZATION (5–15 min per symbol)
**Complete parameter tuning on 180 days of data**

```bash
# Via Telegram
/optimize BTC
/optimize BTC ETH SOL   # All 3 symbols
```

Or via CLI:
```bash
cd ~/hyperliquid-trading-bot
source venv/bin/activate
python optimizer.py               # BTC, ETH, SOL all
python optimizer.py --symbol BTC  # Single symbol
python optimizer.py --workers 8   # Parallel (faster)
```

**What it tests:**

| Parameter | Grid |
|-----------|------|
| `spike_threshold_pct` | 0.5, 0.75, 1.0, 1.25, 1.5 |
| `bb_std_multiplier` | 1.0, 1.5, 2.0, 2.5, 3.0 |
| `sl_pct` | 0.003, 0.004, 0.005, 0.006, 0.007 |
| `tp_pct` | 0.010, 0.012, 0.015, 0.020, 0.025 |
| `position_size_pct` | 0.005, 0.01, 0.015, 0.02 |
| `max_hold_hours` | 12, 24, 36, 48 |

**Output:**
- `optimization_results/optimization_results_BTC_<DATE>.csv`
- `optimization_results/optimization_summary.md`
- `best_params.json` (top-3 combos)
- Top 10 results sent to Telegram

**Expected Result:** Best params ready for live deployment

---

### Option B: BACKTEST ON RECENT DATA (1–5 min)
**Validate params on out-of-sample data before going live**

```bash
# Via Telegram
/backtest BTC 30                          # Last 30 days, current params
/backtest BTC 30 --use-optimized-params   # Last 30 days, best optimized params
/backtest ETH 14                          # 14 days
```

**Expected Result:**
```
✅ Backtest Results — BTC (last 30 days)
Sharpe: 2.14 | Return: +3.2% | Drawdown: 8.1% | Trades: 24
Status: READY TO TRADE
```

**What to look for:**
- **Sharpe > 1.0** — Good risk-adjusted returns
- **Win Rate > 55%** — More wins than losses
- **Max DD < 20%** — Acceptable drawdown
- **Trades ≥ 20** — Statistical relevance

---

### Option C: QUICK SIGNAL CHECK (instant)
**Test framework without optimization**

In Telegram:
```
/analyze BTC
```

Shows:
- ✅ Current spike detection status
- ✅ Bollinger Band reading (upper/lower/current)
- ✅ Signal: LONG / SHORT / NONE
- ✅ Entry, SL, TP prices

Or run the strategy directly:
```bash
python3 -c "
from strategy_engine import VMRConfig, VMRStrategy
from vmr_trading_bot import DataFetcher

config   = VMRConfig()
strategy = VMRStrategy(config)
fetcher  = DataFetcher()
df       = fetcher.get_candles('BTC', days=7)
signal   = strategy.analyze(df, 'BTC')
print(f'Signal: {signal.direction}')
print(f'Confidence: {signal.confidence:.2f}')
print(f'Reason: {signal.reason}')
"
```

---

## 🎯 RECOMMENDED TEST FLOW

### Before Live Trading

```
Day 1: Option C — Quick signal check
        → Does strategy detect signals on today's data?

Day 2: Option A — Run full optimization
        → What params work best on 180d history?

Day 3: Option B — Backtest with optimized params
        → Do the best params hold up on the last 30 days (out-of-sample)?

Day 4: Paper Trading — Start loop in paper mode
        /start_auto   (with HL_SECRET_KEY removed from .env)
        → Monitor for 1–2 days

Day 5+: Go Live on Testnet
        (set HL_SECRET_KEY in .env, keep HL_TESTNET=true)
        /set_params size=0.005   # Start small
        /start_auto
```

---

## 📈 INTERPRETING RESULTS

### Optimization Output Example

```
🏆 Top 3 Parameter Sets

#1: spike=1.0% | bb=3.0 | sl=0.6% | tp=2.5% | size=1% | hold=12h
   BTC Sharpe: 2.72 | Return: +18.3% | Drawdown: 12.1% | Trades: 87

#2: spike=0.8% | bb=2.5 | sl=0.5% | tp=2.0% | size=1% | hold=12h
   BTC Sharpe: 2.61 | Return: +17.1% | Drawdown: 13.2% | Trades: 92
```

**What to pick:**
- **Conservative:** `sharpe > 1.5`, `drawdown < 15%`, `win_rate > 65%`
- **Balanced:** Top result from `/show_best_params` (optimized for Sharpe)
- **Aggressive:** `sharpe > 2.0`, `return > 15%` (accept higher drawdown)

### Backtest Output Example

```
✅ Paper trade complete!
   P&L: +$183.50 (+1.84%)
   Trades: 24
   Win Rate: 68%
   Max Drawdown: 8.3%
```

---

## ⚠️ SAFETY CHECKS (Before Going Live)

Always verify these before `/start_auto` in LIVE mode:

1. **Params validated via backtest**
   ```
   /backtest BTC 30 --use-optimized-params
   # Sharpe > 1.0 and drawdown < 20%
   ```

2. **Mode confirmed**
   ```
   /mode
   # Should show LIVE (or PAPER if still testing)
   ```

3. **Balance visible**
   ```
   /balance
   # Shows real balance from Hyperliquid
   ```

4. **Daily loss limit set**
   ```
   # In strategy_engine.py: daily_loss_limit_pct = 0.05 (5%)
   # Bot stops new trades if daily loss ≥ 5%
   ```

5. **Position size small**
   ```
   /set_params size=0.005   # 0.5% per trade — start conservative
   ```

---

## 🚀 GOING LIVE CHECKLIST

Before `/start_auto` with real money:

- [ ] Ran `/optimize BTC ETH SOL` and reviewed results
- [ ] Ran `/backtest BTC 30 --use-optimized-params` — Sharpe > 1.0, DD < 20%
- [ ] Paper-traded 24–48h with loop running
- [ ] `/mode` shows correct mode (LIVE/PAPER)
- [ ] Position size is small (`size=0.005` to start)
- [ ] `HL_TESTNET=true` confirmed before going mainnet
- [ ] `best_params.json` saved as backup

---

## 📊 MONITORING AFTER LIVE START

```bash
# In Telegram
/status       # Current positions, unrealised P&L, loop health
/stats        # Completed trades, win rate, total P&L
/balance      # Account balance, daily P&L, loss limit status

# Log file
tail -f vmr_bot.log   # Real-time activity log
```

**Kill-switch (emergency stop):**
```
/stop_all     # Telegram: stops loop + closes all positions at market
```

Or via shell:
```bash
pkill -f "python vmr_trading_bot.py"
# Then log in to app.hyperliquid.xyz to close open positions
```

---

## 🧠 TUNING CHECKLIST

After first week of live trading:

- [ ] Check win rate via `/stats` (target: > 55%)
- [ ] Check max drawdown (should be < 15% with default params)
- [ ] Review Sharpe ratio trend
- [ ] If too few trades: lower `spike_threshold_pct`
  - `/set_params spike=0.7`
- [ ] If too many losing trades: raise threshold or tighten filter
  - `/set_params spike=1.2 bb_mult=2.5`
- [ ] Re-run `/optimize` every 2–4 weeks with fresh data

---

## 💡 QUICK REFERENCE

| Action | Command / Tool | Time |
|--------|---------------|------|
| Run full optimization | `/optimize BTC ETH SOL` | 5–15 min |
| Quick backtest | `/backtest BTC 30` | 1–3 min |
| Check current signal | `/analyze BTC` | instant |
| Show best params | `/show_best_params` | instant |
| Update params | `/set_params spike=1.0 ...` | instant |
| Start trading | `/start_auto` | instant |
| Emergency stop | `/stop_all` | instant |
| Run CLI optimizer | `python optimizer.py --symbol BTC` | 5–15 min |

---

## ✅ You're Ready!

- ✅ VMR signal detection built and tested
- ✅ Parameter optimization covers 10,000+ combinations
- ✅ Backtest uses real Hyperliquid 1h candle data (no synthetic data)
- ✅ Paper trading mode for risk-free validation
- ✅ Telegram commands for full control

**Pick an option above and start testing!** 🎯
