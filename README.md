# Hyperliquid Trading Bot

A Python-based trading bot for [Hyperliquid](https://hyperliquid.xyz) with FastAPI REST API, Telegram integration, and built-in risk management.

**Status:** Phase 1 — Foundation (repo scaffold, API, risk manager, Telegram bot skeleton)

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

## Risk Management

- **Daily Drawdown Cap:** Stops trading if daily loss exceeds configured % (default: 5%)
- **Circuit Breaker:** Stops trading after N consecutive losses (default: 3)
- **Position Sizing:** Calculates size as % of current balance (default: 2%)

## Roadmap

- [x] Phase 1: Foundation (repo, API, risk manager, Telegram)
- [ ] Phase 2: Strategy engine + backtesting
- [ ] Phase 3: Live trading + monitoring

## License

Private — not for distribution.
