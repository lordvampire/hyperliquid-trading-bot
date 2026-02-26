# Hyperliquid Trading Bot

A Python-based trading bot for [Hyperliquid](https://hyperliquid.xyz) with FastAPI REST API, Telegram integration, and built-in risk management.

**Status:** Phase 2 — Real Strategy Engine (live sentiment + funding rates + realistic backtesting)

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
| `HL_SECRET_KEY` | Your Hyperliquid private key (testnet!) |
| `HL_WALLET_ADDRESS` | Your wallet address |
| `HL_TESTNET` | `true` for testnet, `false` for mainnet |
| `TELEGRAM_BOT_TOKEN` | From @BotFather |
| `TELEGRAM_CHAT_ID` | Your Telegram chat ID |

### 4. Run

**API Server:**
```bash
python main.py
# → http://localhost:8000
# → http://localhost:8000/docs (Swagger UI)
```

**Telegram Bot** (separate terminal):
```bash
python bot.py
```

### 5. Test

```bash
# Health check
curl http://localhost:8000/health

# Account status
curl http://localhost:8000/status

# Unit tests
pytest tests/ -v
```

## API Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Health check + config validation |
| GET | `/status` | Balance, positions, risk status |
| POST | `/order` | Place order (stubbed in Phase 1) |
| GET | `/candles?symbol=BTC&interval=1h` | OHLCV candles |
| GET | `/risk` | Risk manager status |

## Telegram Commands

| Command | Description |
|---|---|
| `/start` | Activate bot |
| `/status` | Full status (balance + positions + risk) |
| `/balance` | Account balance only |
| `/risk` | Risk manager status |

## Project Structure

```
├── main.py          # FastAPI server
├── bot.py           # Telegram bot
├── exchange.py      # Hyperliquid SDK wrapper
├── manager.py       # Risk manager (DD cap, circuit breaker)
├── db.py            # SQLite schema + queries
├── config.py        # Environment config
├── tests/
│   └── test_risk_manager.py
├── requirements.txt
├── example.env
└── README.md
```

## Architecture — Phase 2

```
┌─────────────────────────────────────────────────────────┐
│                    Hyperliquid API                      │
│  • Real-time funding rates   • OHLCV candles            │
│  • Account state            • Trade execution           │
└──────────────────┬──────────────────────────────────────┘
                   │
         ┌─────────┴─────────┐
         │                   │
    ┌────▼────┐        ┌────▼───────┐
    │ funding │        │  exchange  │
    │  .py    │        │    .py     │
    └────┬────┘        └────────────┘
         │                 (raw API)
         │
    ┌────▼──────────────┐
    │  sentiment.py     │
    │ (heuristic engine)│     Input: Funding trends + volatility
    └────┬──────────────┘     Output: BUY/SELL/HOLD signals
         │
         └──────────┬──────────────┐
                    │              │
            ┌───────▼────┐    ┌────▼──────────┐
            │ strategy_b │    │  backtest.py  │
            │    .py     │    │  (validation) │
            │  (router)  │    └───────────────┘
            └───────┬────┘
                    │
         ┌──────────┴────────────┐
         │                       │
    ┌────▼──────────┐   ┌───────▼────────┐
    │    main.py    │   │ testnet_runner │
    │   (REST API)  │   │    .py         │
    └───────────────┘   │  (validation)  │
                        └────────────────┘
                              │
                        ┌─────▼──────┐
                        │   SQLite   │
                        │  (logging) │
                        └────────────┘
```

**Data Flow:**
1. **funding.py** → Fetches real funding rates (1h cache)
2. **sentiment.py** → Analyzes trends (40% funding trend, 30% current level, 30% volatility)
3. **strategy_b.py** → Combines sentiment + funding, generates signals
4. **backtest.py** → Validates on historical data (fees included)
5. **testnet_runner.py** → Runs live validation with logging
6. **SQLite** → Stores all decisions for analysis

## Risk Management

- **Daily Drawdown Cap:** Stops trading if daily loss exceeds configured % (default: 5%)
- **Circuit Breaker:** Stops trading after N consecutive losses (default: 3)
- **Position Sizing:** Calculates size as % of current balance (default: 2%)
- **Fee Modeling:** 0.02% entry + 0.06% exit in backtesting (realistic costs)

## Phase 2: Strategy Engine (LIVE)

### What's New

**Real Data Integration** — No more fake values:

- **Sentiment Analysis**: Heuristic-based sentiment using:
  - Funding rate trends (24h moving direction)
  - Current funding level (high positive = bearish; high negative = bullish)  
  - Volatility in funding (indicator of conviction)
  - Generates signals: BUY, SELL, HOLD with confidence scores

- **Funding Rates**: Real-time from Hyperliquid API:
  - Fetches actual funding history via `/info/fundingHistory`
  - 1-hour cache to avoid API hammering
  - Signals: LONG (pay less), SHORT (collect), NEUTRAL

- **Backtesting**: Realistic P&L on historical candles:
  - Uses real OHLCV from Hyperliquid
  - Realistic trading costs: 0.02% entry fee, 0.06% exit fee
  - Includes funding paid over position duration
  - Simulates SL/TP exits (5% each way from entry)
  - Reports win rate, ROI, and per-trade details

### How Strategy B Works

1. **Sentiment Analysis** (40% weight):
   - Analyze funding trends: RISING → bullish, FALLING → bearish
   
2. **Funding Signal** (30% weight):
   - High positive funding → shorters paying, take SHORT position
   - High negative funding → longs paying, take LONG position
   
3. **Combined Score**:
   - If sentiment + funding align (both bullish or both bearish) → STRONG signal
   - Otherwise → HOLD

4. **Entry**:
   - Only when combined confidence > 30%
   - Position size = 2% of balance (risk controlled)

5. **Exit**:
   - Take profit: 5% above entry (long) or below entry (short)
   - Stop loss: 5% below entry (long) or above entry (short)
   - Signal reversal: if sentiment flips, close position

### Example Trade Log

```
Timestamp: 2026-02-26T09:00:00
Symbol: BTC
Sentiment: RISING funding, avg rate +0.000013 → BULLISH
Funding: Current rate -0.000025 (low negative) → NEUTRAL
Combined Score: +0.20 (low confidence) → HOLD

---

Timestamp: 2026-02-26T12:00:00
Symbol: ETH
Sentiment: FALLING funding, avg rate -0.000008 → BEARISH
Funding: Current rate +0.000045 (high positive) → SHORT
Combined Score: -0.65 (strong confidence) → SELL
Position: Short 10 ETH @ $2500
Exit: Take profit @ $2375 (5% below entry) = +$1,250 profit
```

### Testing Phase 2

Run the validation suite:
```bash
python3 test_phase2.py
```

This tests:
- Real funding rate API integration
- Sentiment analysis with live data
- Backtest engine with historical candles
- Strategy B signal generation

### Testnet Validation

Run Phase 2 strategy on testnet with automated logging:

```bash
# Quick test: 30 minutes, BTC + ETH
python3 testnet_runner.py --duration 30

# Full validation: 12 hours (720 minutes)
python3 testnet_runner.py --duration 720

# Custom symbols, 24-hour run
python3 testnet_runner.py --duration 1440 --symbols BTC,ETH,SOL
```

This will:
- ✓ Check signals every 30 minutes (configurable)
- ✓ Log all signals to SQLite (test_trades table)
- ✓ Track sentiment + funding components
- ✓ Generate final report with statistics
- ✓ Show signal decision tree for each check

Database queries after run:
```sql
-- All signals from test run
SELECT timestamp, symbol, signal, action FROM test_trades 
WHERE test_run_id = '20260226_093700' 
ORDER BY timestamp;

-- Summary statistics
SELECT * FROM test_run_summary 
WHERE test_run_id = '20260226_093700';
```

## Roadmap

- [x] Phase 1: Foundation (repo, API, risk manager, Telegram)
- [x] Phase 2: Real Strategy Engine (sentiment, funding, backtesting)
- [ ] Phase 3: Testnet validation + live trading

## License

Private — not for distribution.
