# User Manual — VMR Trading Bot

**Version:** 2.0  
**Last Updated:** March 1, 2026

---

## Table of Contents

1. [Setup & First Run](#setup--first-run)
2. [Telegram Commands Reference](#telegram-commands-reference)
3. [Parameter Optimization Workflow](#parameter-optimization-workflow)
4. [Trading Workflows](#trading-workflows)
5. [Monitoring & Troubleshooting](#monitoring--troubleshooting)
6. [FAQ](#faq)

---

## Setup & First Run

### 1. Install Dependencies

```bash
cd hyperliquid-trading-bot
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get Credentials

**Hyperliquid Testnet Wallet:**
- Go to https://app.hyperliquid-testnet.xyz
- Sign up with email
- Generate private key → copy to `.env` as `HL_SECRET_KEY`
- Copy wallet address → `HL_WALLET_ADDRESS`

**Telegram Bot Token:**
- Chat with @BotFather on Telegram
- `/newbot`
- Copy token → `.env` as `TELEGRAM_BOT_TOKEN`
- Get your user ID: `/start` in @userinfobot → copy to `TELEGRAM_CHAT_ID`

### 3. Configure `.env`

```bash
cp .env.example .env
# Edit with your values
```

**Example:**
```
HL_SECRET_KEY=33f9dae8512c75f375d15b8c4bd22813f004c9009c8c9405f4a8da618db9fbe0
HL_WALLET_ADDRESS=0x754E13410553c25D8797979962ea271b2c5B2A9e
HL_TESTNET=true
HL_DRY_RUN=false

TELEGRAM_BOT_TOKEN=8568129217:AAEj8EUljihDtMYC_ILXgz9QwF0RsK4oJgk
TELEGRAM_CHAT_ID=5890731372
```

### 4. Start Bot

```bash
python vmr_trading_bot.py
```

Expected output:
```
2026-03-01 12:29:10,502 - [INFO] - LiveTrader initialising — TESTNET
2026-03-01 12:29:12,362 - [INFO] - ✅ Info client ready
2026-03-01 12:29:12,362 - [INFO] - ✅ Bot ready. Polling for Telegram messages...
```

### 5. Send `/start` in Telegram

Bot replies with current status and available commands.

---

## Telegram Commands Reference

### 🎯 Core Trading Commands

#### `/start_auto`
Starts the autonomous trading loop. Bot will scan for signals every 15 minutes.

```
/start_auto
```

Response:
```
✅ Autonomous trading started
Scan interval: 900 seconds (15 min)
Symbols: BTC, ETH, SOL
Monitoring...
```

Bot will now:
- Fetch latest 1h candles for all symbols
- Run VMR signal detection
- Execute trades when signals fire
- Send Telegram notifications for each trade

#### `/stop_auto`
Stops the autonomous loop **but keeps positions open**.

```
/stop_auto
```

Use this to pause trading while reviewing positions.

#### `/stop_all`
Stops the loop **and closes all open positions at market**.

```
/stop_all
```

Use when you want to exit everything immediately.

#### `/status`
Shows current positions, P&L, account balance, and scan status.

```
/status
```

Response:
```
📊 PAPER TRADING STATUS
Account: $10,000.00 | In Positions: $3,300.00 | Free: $6,700.00
ROI: +2.34%

📍 Open Positions (2/3):
BTC: LONG | Entry $65,000 | Current $65,500 | P&L: +$500 (+1.52%)
ETH: SHORT | Entry $2,500 | Current $2,480 | P&L: +$100 (+1.61%)

SOL: No position

Scan Status: RUNNING (last scan 3m ago)
Next scan: 12:15 PM
```

#### `/stats`
Shows closed trade statistics.

```
/stats
```

Response:
```
📈 Closed Trades Summary
Total: 5 | Won: 3 (60%) | Lost: 2 (40%)
Total P&L: +$1,200 | Win Rate: 60%
Avg Win: +$500 | Avg Loss: -$200
Largest Win: +$800 | Largest Loss: -$400
```

---

### 🔍 Analysis & Optimization Commands

#### `/analyze [BTC|ETH|SOL]`
One-shot signal analysis for a specific symbol.

```
/analyze BTC
```

Response:
```
📊 BTC Signal Analysis (current)
Candle (1h): O:65,200 | H:65,500 | L:65,100 | C:65,400
Return: +0.31%

Bollinger Bands (20, 2σ):
Upper: 65,800 | Mid: 65,200 | Lower: 64,600
Price relative: WITHIN bands

Volatility: 1.23% (rolling 20h std)
Status: NO SIGNAL (return too small)
```

#### `/signals`
Shows latest signal for all 3 symbols at once.

```
/signals
```

Response:
```
📡 Latest VMR Signals

BTC: NO SIGNAL | Return +0.31% | Vol 1.23%
ETH: LONG (weak) | Return -0.85% | Vol 2.14%
SOL: SHORT (strong) | Return +1.42% | Vol 2.67%
```

#### `/optimize [SYM1] [SYM2] ...`
Runs parameter optimization on specified symbols (or all 3 if none given).

```
/optimize BTC
/optimize BTC ETH SOL
/optimize
```

Process:
- Fetches 180 days of 1h candles (first run takes ~30s)
- Tests 10,000+ parameter combinations
- Scores by Sharpe ratio, max drawdown, win rate
- Saves results to `optimization_results/`
- Sends progress updates to Telegram

Response (after ~5 min):
```
✅ Optimization complete (5m 23s)

🏆 Top Results for BTC:
#1: spike=1.0% | bb=3.0 | sl=0.6% | tp=2.5% | Sharpe=2.72
#2: spike=0.8% | bb=2.5 | sl=0.5% | tp=2.0% | Sharpe=2.61
#3: spike=1.2% | bb=3.0 | sl=0.6% | tp=2.0% | Sharpe=2.44

Run /show_best_params to see full details
```

#### `/show_best_params`
Displays the top 3 parameter sets from the last optimization run.

```
/show_best_params
```

Response:
```
🏆 Top 3 Parameter Sets

#1: spike=1.0% | bb=3.0 | sl=0.6% | tp=2.5% | size=1% | hold=12h
    BTC: Sharpe 2.72 | Return +18.3% | DD 12.1% | Trades 87
    ETH: Sharpe 0.74 | Return +5.2% | DD 18.3% | Trades 53
    SOL: Sharpe 2.30 | Return +15.7% | DD 14.2% | Trades 76

#2: spike=0.8% | bb=2.5 | sl=0.5% | tp=2.0% | size=1% | hold=12h
    BTC: Sharpe 2.61 | Return +17.1% | DD 13.2% | Trades 92
    ETH: Sharpe 0.68 | Return +4.9% | DD 19.1% | Trades 58
    SOL: Sharpe 2.15 | Return +14.2% | DD 15.3% | Trades 81

#3: spike=1.2% | bb=3.0 | sl=0.6% | tp=2.0% | size=1% | hold=12h
    BTC: Sharpe 2.44 | Return +16.1% | DD 14.2% | Trades 78
    ETH: Sharpe 0.62 | Return +4.2% | DD 20.1% | Trades 48
    SOL: Sharpe 2.08 | Return +13.5% | DD 16.1% | Trades 71
```

#### `/backtest [BTC|ETH|SOL] [DAYS]`
Backtests current or optimized params on historical data.

```
/backtest BTC 30
/backtest BTC 30 --use-optimized-params
/backtest BTC       # Defaults to 30 days
```

Response:
```
📊 Backtest Results (BTC, last 30 days)
Sharpe Ratio: 2.14
Total Return: +3.2%
Max Drawdown: 8.1%
Win Rate: 72.7%
Trades Executed: 24
Avg Hold Time: 4.2h

Status: ✅ READY TO TRADE
(Sharpe > 1.0, DD < 25%, Win rate > 60%)
```

---

### ⚙️ Configuration Commands

#### `/set_params [param=value] ...`
Updates VMR strategy parameters live (bot keeps running).

```
/set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
```

Available parameters:
- `spike` — 1h return spike threshold (0.3–1.5)
- `bb_mult` — Bollinger Band std multiplier (1.0–3.0)
- `sl` — Stop-loss percentage (0.003–0.008)
- `tp` — Take-profit percentage (0.010–0.025)
- `size` — Position size as % of account (0.01–0.05)
- `hold` — Max hold hours (1–48)

Response:
```
✅ Parameters updated
Previous: spike=1.0% | bb=2.0 | sl=0.5% | tp=1.5%
New:      spike=1.0% | bb=3.0 | sl=0.6% | tp=2.5%

New params apply to next signal execution.
Current positions keep original params.
```

#### `/balance`
Shows account balance and risk settings.

```
/balance
```

Response:
```
💰 Account Balance
Mode: LIVE TESTNET
Total Balance: $998.76 USDC
In Positions: $0.00
Available: $998.76

Risk Settings:
Max Daily Loss: 5.0%
Max Open Positions: 3
Leverage Range: 5–10x

Current Leverage: 0x (no open positions)
```

#### `/help`
Shows all available commands.

```
/help
```

---

## Parameter Optimization Workflow

### Scenario 1: First-Time Setup (Best Params Unknown)

**Goal:** Find optimal params for your account.

**Steps:**

1. **Optimize on historical data:**
   ```
   /optimize BTC ETH SOL
   ```
   Wait 5–7 minutes for completion.

2. **Review results:**
   ```
   /show_best_params
   ```
   Check Sharpe, return, drawdown for all 3 symbols.

3. **Validate on out-of-sample data:**
   ```
   /backtest BTC 30 --use-optimized-params
   /backtest ETH 30 --use-optimized-params
   /backtest SOL 30 --use-optimized-params
   ```
   Ensure all show positive Sharpe and < 25% drawdown.

4. **Apply best params:**
   ```
   /set_params spike=1.0 bb_mult=3.0 sl=0.006 tp=0.025 size=0.01 hold=12
   ```
   (Use values from #1 `spike` set.)

5. **Start trading:**
   ```
   /start_auto
   ```

---

### Scenario 2: Market Regime Changed (Params Not Working)

**Goal:** Re-optimize to adapt to new market conditions.

**Steps:**

1. **Stop current trades:**
   ```
   /stop_auto
   ```

2. **Re-optimize on fresh data:**
   ```
   /optimize BTC ETH SOL
   ```
   (Fetches latest 180 days, ignores old cache.)

3. **Backtest new params:**
   ```
   /backtest BTC 14 --use-optimized-params
   ```
   Use last 2 weeks to see if params work in recent market.

4. **Apply if good:**
   ```
   /set_params ...
   /start_auto
   ```

---

### Scenario 3: Tuning Specific Behavior

**Goal:** Adjust for specific market style (more/fewer trades, tighter stops, etc.)

**Steps:**

1. **Identify issue:**
   - Too few trades? → Lower `spike_threshold`
   - Too many losses? → Raise `spike_threshold`, tighten `sl_pct`
   - Positions hold too long? → Lower `tp_pct` or `max_hold_hours`

2. **Make small changes:**
   ```
   /set_params spike=0.9  # Was 1.0
   ```
   Test for 1 hour.

3. **Backtest if needed:**
   ```
   /backtest BTC 7 --use-optimized-params
   ```

4. **Finalize:**
   ```
   /set_params spike=0.9 ...
   ```

---

## Trading Workflows

### Workflow 1: Paper Trading (No Real Money)

Use for testing and learning.

**Setup:**
```bash
# In .env:
HL_DRY_RUN=true    # Validates orders but doesn't execute
PAPER_BALANCE=10000.0
```

**Trading:**
```
/start_auto
```

Bot simulates trades on `PAPER_BALANCE`. No real orders sent to Hyperliquid.

**Monitor:**
```
/status
/stats
```

**Advantages:**
- Risk-free
- Fast testing of params
- No fees or slippage

**Disadvantages:**
- Doesn't match live execution exactly
- No real market impact

---

### Workflow 2: Live Testnet (Real Hyperliquid, Play Money)

Test on real exchange with play money.

**Setup:**
```bash
# In .env:
HL_TESTNET=true    # Connect to Hyperliquid testnet
HL_DRY_RUN=false   # Execute real orders
```

**Fund your testnet wallet:**
- Go to https://app.hyperliquid-testnet.xyz
- Faucet → request testnet USDC

**Trading:**
```
/start_auto
```

Bot places real orders on Hyperliquid testnet.

**Monitor:**
```
/status
/stats
```

**Advantages:**
- Real order execution
- Real fees & slippage
- Real market conditions
- No money at risk (testnet only)

**Disadvantages:**
- Slower than paper (exchange latency)
- More complex to debug

---

### Workflow 3: Live Mainnet (REAL MONEY) — Not Recommended for New Users

Deploy on mainnet with real capital.

⚠️ **Only after:**
- Successful testnet run (≥50 trades)
- Backtests show Sharpe > 1.5
- You fully understand the strategy
- You can afford to lose the capital

**Setup:**
```bash
# In .env:
HL_TESTNET=false   # Connect to Hyperliquid mainnet
HL_DRY_RUN=false   # Execute real orders with REAL MONEY
```

**Deployment:** See [DEPLOYMENT.md](./DEPLOYMENT.md)

---

## Monitoring & Troubleshooting

### Check Bot Status

```bash
# Is bot process running?
ps aux | grep vmr_trading_bot

# Check logs
tail -100 vmr_bot.log

# Search for errors
tail -500 vmr_bot.log | grep ERROR
```

### Common Issues

#### Issue: "No trades for hours"

**Cause:** Market is calm, no volatility spikes.

**Solution:**
```
/analyze BTC
# Check if return is below spike_threshold

/set_params spike=0.7  # Lower threshold
# Test for 30 min

/backtest BTC 7
# Does lower threshold improve results?
```

---

#### Issue: "Too many losing trades"

**Cause:** Threshold too low, catching noise.

**Solution:**
```
/stats
# Check win rate. If < 50%, threshold too low.

/set_params spike=1.2  # Raise threshold
# Or run /optimize to find better params
```

---

#### Issue: "Telegram messages delayed"

**Cause:** Network lag or Telegram API overload.

**Solution:**
```
# Check bot logs for API errors
tail -50 vmr_bot.log | grep -i "telegram\|error"

# Restart bot
pkill -f vmr_trading_bot.py
python vmr_trading_bot.py
```

---

#### Issue: "Backtest shows good results, but live trading loses"

**Cause:** Overfitting to historical data or slippage in real execution.

**Solution:**
```
# Validate on more recent data
/backtest BTC 14 --use-optimized-params
# Should still be positive

# Try less aggressive params
/set_params tp=1.5 size=0.005  # Tighter TP, smaller size
/start_auto

# Compare live results after 20+ trades
/stats
```

---

### Reading the Logs

```
vmr_bot.log
```

Key messages:

```
2026-03-01 12:29:10 - [INFO] - Fetching BTC candles (7d)...
→ Bot is fetching data

2026-03-01 12:29:11 - [INFO] - ✅ Got 169 candles for BTC
→ Data fetch successful

2026-03-01 12:30:00 - [INFO] - 📡 Signals: BTC=NONE ETH=LONG SOL=NONE
→ Latest signal detection (no entry yet)

2026-03-01 12:30:05 - [INFO] - 🔴 LIVE TRADE OPENED: ETH LONG @ $2,500
→ Real order executed!

2026-03-01 12:45:00 - [INFO] - 🔴 LIVE TRADE CLOSED: ETH LONG exit TP @ $2,537.50
→ Position closed with take-profit hit

[ERROR] → Something went wrong (check details above error line)
```

---

## FAQ

### Q: How often does the bot scan for signals?

**A:** Every 15 minutes (default). Controlled by `scan_interval_seconds` in `VMRConfig`.

To change:
```
# In strategy_engine.py, line ~80:
scan_interval_seconds: int = 900  # 900 sec = 15 min
# Change to 600 for 10 min, 1800 for 30 min, etc.
# Restart bot for change to take effect
```

---

### Q: Can I trade with different symbols?

**A:** Currently only BTC, ETH, SOL. To add more:

```
# In vmr_trading_bot.py, line ~70:
CFG = VMRConfig(
    symbols=["BTC", "ETH", "SOL", "ARB"],  # Add new symbol
)
```

Restart bot.

---

### Q: What if I want to keep 1 position open longer?

**A:** Increase `max_hold_hours`:

```
/set_params hold=48  # Allow 48-hour holds instead of 24h
```

---

### Q: Can I run multiple bots in parallel?

**A:** Not recommended. Multiple bot instances will fight for order execution.

Instead, use `/set_params` to adjust a single bot's behavior.

---

### Q: How do I export trade history?

**A:** View completed trades:

```
/stats
```

For detailed CSV export, open bot logs and parse.

---

### Q: Should I restart the bot daily?

**A:** No, not necessary. Bot runs 24/7 unless you stop it.

Restart only if:
- You update `.env` config
- You modify `strategy_engine.py`
- Bot crashes (check logs for why)

---

### Q: What's the difference between `/backtest` and `/optimize`?

**A:**

| Command | What it does | Time | Use case |
|---------|------------|------|----------|
| `/backtest BTC 30` | Tests CURRENT params on last 30d | 5 sec | Validate before trading |
| `/optimize BTC` | Tests 10k+ param combos on 180d | 5 min | Find best params |

---

### Q: Can I set different params per symbol?

**A:** Currently no, params are global (all symbols use same settings).

Workaround: Run multiple bots (advanced, not recommended).

---

### Q: How much capital do I need?

**A:** Testnet: None (use faucet for play money).

Mainnet: Depends on risk tolerance:
- **Conservative:** $1,000+ (1% position size = $10 per trade)
- **Aggressive:** $5,000+ (allows larger positions, more flexibility)

Position size is adjustable via `/set_params size=X`.

---

### Q: What if the API goes down?

**A:** Bot will log errors and retry automatically. Check logs:

```bash
tail vmr_bot.log | grep -i "error\|fail"
```

If errors persist, restart bot:
```bash
pkill -f vmr_trading_bot.py
python vmr_trading_bot.py
```

---

## Next Steps

1. **Complete Setup:** Follow [Setup & First Run](#setup--first-run)
2. **Optimize Params:** Run `/optimize BTC ETH SOL`
3. **Paper Trade:** Start with `HL_DRY_RUN=true` to test
4. **Go Live (Testnet):** Switch to `HL_DRY_RUN=false`
5. **Monitor:** Check `/status` and `/stats` regularly

Good luck! 🚀
