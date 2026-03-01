# v2 Signal Library — Standalone Multi-Signal Modules

> **Note:** The v2/ folder contains signal detector modules built in February 2026 as part of a planned multi-signal framework. These modules are **standalone and functional**, but are **NOT used by the main production bot**.
>
> The production bot uses the **VMR (Volatility Mean Reversion)** strategy implemented in:
> - `vmr_trading_bot.py` — Main bot (Telegram + loop)
> - `strategy_engine.py` — VMR strategy engine (single source of truth)
> - `live_trader.py` — Hyperliquid order execution
> - `optimizer.py` — VMR parameter optimizer
>
> **For production usage:** See the top-level [README.md](../README.md) and [README_VMR.md](../README_VMR.md).

---

## What's in v2/

The v2/ directory contains completed signal detector modules that can be used as independent libraries or integrated into a future strategy.

### `v2/signals/`

| Module | Status | Description |
|--------|--------|-------------|
| `volatility_regime.py` | ✅ Complete | Classifies market volatility into LOW/MEDIUM/HIGH regimes using ATR(20), Bollinger Band width, and historical vol percentile |
| `price_momentum.py` | ✅ Complete | Detects directional momentum using RSI(14), MACD, and Rate of Change (ROC) |
| `orderbook_imbalance.py` | ✅ Complete | Detects bid/ask order book imbalance (whale accumulation/distribution) |
| `combined_signal.py` | ✅ Complete | Combines all 4 signals: 40% Vol + 30% Momentum + 20% OB + 10% Funding |

### `v2/tests/`

| Test File | Status | Coverage |
|-----------|--------|----------|
| `test_volatility_regime.py` | ✅ 29 tests | 92% |
| `test_price_momentum.py` | ✅ 47 tests | 95% |
| `test_orderbook_imbalance.py` | ✅ Complete | — |
| `test_combined_signal.py` | ✅ Complete | — |

---

## Running v2 Tests

```bash
cd ~/hyperliquid-trading-bot
source venv/bin/activate

# All v2 tests
pytest v2/tests/ -v

# Specific module
pytest v2/tests/test_volatility_regime.py -v
pytest v2/tests/test_price_momentum.py -v
```

---

## Using v2 Modules Independently

### Volatility Regime Detection

```python
from v2.signals.volatility_regime import VolatilityRegimeDetector

detector = VolatilityRegimeDetector()
result = detector.analyze(symbol="BTC", candles=[...])
# Returns: {"regime": "HIGH", "atr": 1250.5, "bb_width": 0.024, "hist_vol_percentile": 78}
```

### Price Momentum Detection

```python
from v2.signals.price_momentum import PriceMomentumDetector

detector = PriceMomentumDetector()
result = detector.analyze(symbol="BTC", candles=[...])
# Returns: {"signal": "STRONG_UP", "rsi": 65, "macd": 1200, "roc": 2.3}
```

### Combined Signal

```python
from v2.signals.combined_signal import CombineSignalDetector, CompositeSignal

detector = CombineSignalDetector()
result = detector.analyze(vol_signal, momentum_signal, ob_signal, funding_signal)
# Returns: CompositeSignal with BUY/SELL/HOLD + confidence score
```

---

## Background: Why These Were Built

In February 2026, a Perplexity Sonar analysis critiqued the v1 funding-rate strategy and recommended a multi-signal approach. A 4-phase roadmap was created to build:

1. Volatility-Regime Detector (40% signal weight)
2. Price-Momentum Detector (30% signal weight)
3. Order-Book Imbalance Detector (20% signal weight)
4. Composite Signal Combiner

All 4 signal modules were implemented. However, the production strategy was built as VMR (Volatility Mean Reversion) instead — a simpler, proven-edge approach using spike detection + Bollinger Band confirmation with a full parameter optimizer.

The v2 signal modules remain available as a library and could be integrated into future strategy iterations.

---

## Documentation Index

For historical planning context:

- `docs/PERPLEXITY_ANALYSIS.md` — Original critique of v1
- `docs/IMPROVEMENTS.md` — Improvement plan (archived)
- `docs/ROADMAP.md` — 4-week build roadmap (archived)
- `docs/V2_FEATURE_BREAKDOWN.md` — Feature detail (archived)
- `docs/V2_STATUS.md` — Status snapshot from Feb 2026 (archived)

**Current production docs:**
- `README.md` — VMR overview
- `README_VMR.md` — Detailed VMR guide
- `USER_MANUAL.md` — Full usage manual
- `DEPLOYMENT.md` — Live deployment guide
