# Perplexity Sonar Analysis & Critique
**Date:** 2026-02-26  
**Analysis by:** Perplexity Sonar  
**Status:** Critical Review for Hyperliquid Trading Bot v1

---

## Executive Summary

The bot architecture is technically sound and well-modularized, but the strategy logic is overly simplistic and under-stress-tested for live perpetuals trading. The core risk: **funding-rate-based signals without robust statistics, combined with tight 5% SL/TP + 2% position sizing, creates negative edge probability.**

---

## 1. Core Assumption: Funding-Rate Strategy

### The Problem
- **Funding is mean-reverting, not trending**
  - Funding's purpose (per Hyperliquid docs): reduce arbitrage spread between Perp/Spot
  - When everyone uses it as a signal → overtraded → self-neutralizing
  
- **Heuristic 40/30/30 weighting is arbitrary**
  - No out-of-sample validation
  - No statistical justification
  - Likely overfitted to historical data

- **Lacks secondary confirming signals**
  - Funding alone insufficient
  - No volatility regime filtering
  - No order-book imbalance checks
  - No momentum confirmation

### Impact
Funding-rate signal confidence should be **capped at 20%** of overall score, not 30%.

---

## 2. Strategy Logic ("Strategy B")

### The Problem
- **5% SL/TP in Perpetuals = brutal**
  - High volatility spikes trigger SL before TP
  - Funding cost drain over short holding periods
  - Requires >60% win-rate to be profitable
  
- **No market regime adaptation**
  - Range-bound markets: mean-reversion bias needed
  - Strong trends: momentum bias needed
  - Volatility spikes: position size should reduce
  - Current: one-size-fits-all

- **Funding P&L not in signal logic**
  - Positions close on 5% TP/SL only
  - Ignores accumulated funding cost/gain over hold period
  - Critical design flaw for funding-based strategy

### Impact
Without >60% proven win-rate, this system has **negative expected value**.

---

## 3. Risk Management: Too Static

### The Problem
- **2% position size ignores volatility**
  - No scaling for ATR or implied volatility
  - Correlation risk not addressed
  - Parallel positions in BTC/ETH/SOL can cause systemic drawdown

- **3x Circuit Breaker is arbitrary**
  - 3 losses ≈ 1 in 8 chance with 60% win-rate
  - Too quick to stop potentially profitable system
  - Should use rolling DD-threshold + time-window

- **5% daily DD cap too simplistic**
  - Could be too strict for volatile markets
  - Could be too loose for under-proven strategies
  - No volatility scaling

### Impact
Risk model is **not adaptive** to market conditions.

---

## 4. Backtesting & Data Quality

### The Problem
- **Short holding periods + Funding P&L distortion**
  - 1h candles + tight SL/TP mask Margin-Call risks
  - Slippage/liquidity not modeled
  - Fill quality assumed 100%

- **Look-ahead bias risk**
  - 24h funding trends in backtest may not match real-time calculations
  - 30m candle intervals need precise historical granularity

- **No statistical output**
  - Missing: Win-Rate, Sharpe, Max-DD, R:R, Payoff-Ratio
  - No period analysis (Bull vs Bear market)
  - System feels "sprinkled with logic", not engineered

### Impact
Backtest results are **not reliable** for live deployment.

---

## 5. Testnet Validation: False Confidence

### The Problem
- **Testnet ≠ Real Markets**
  - No real liquidity stress
  - No slippage/realistic fills
  - No extreme funding events
  - 30-1440 min runs = statistically insignificant

- **No stress/edge-case testing**
  - 5-10% crash in 5min scenario?
  - Funding-rate feed timeout?
  - API disconnect handling?
  - Black-swan events?

- **Insufficient duration**
  - 24h max ≈ 48 trades at 30min intervals
  - Minimum required: **7+ days, 100+ signals**

### Impact
Testnet validation **provides false sense of safety**.

---

## 6. Architecture & Real-World Gaps

### The Problem
- **Single-Point-of-Failure (SQLite)**
  - Crash during live run → inconsistent logging
  - No transaction rollback/replay mechanism
  - Position state could be lost

- **Missing Reconnect Logic**
  - No backup API endpoints
  - No position tracking on disconnect
  - Open position = uncontrolled risk

- **No Testnet/Mainnet Separation**
  - Single HL_TESTNET flag
  - One config mistake → live capital loss

### Impact
System **not production-ready** for live trading.

---

## 7. Overall Assessment

### What's Good ✅
- Clean modularization (exchange, sentiment, funding, strategy, risk, db)
- Separate test pathways (unit, backtest, testnet-runner)
- Funding-rate heuristic is conceptually sound (if improved)

### What's Problematic ❌
- Over-reliance on simplistic funding-rate signal
- Tight 5% SL/TP + 2% risk + funding costs = likely negative edge
- Testnet validation insufficient for real markets
- Risk model is too static
- Architecture lacks failover/resilience

### Verdict
**Technically solid, but strategically unproven.**

---

## Required Improvements (See IMPROVEMENTS.md)

1. Multi-signal framework (volatility, momentum, order-book)
2. Dynamic risk sizing (volatility-scaled SL/TP/position)
3. Stress-test framework (black-swan scenarios)
4. Statistical validation (Sharpe, Payoff-Ratio, win-rate >60%)
5. Extended testnet (7+ days)
6. Reconnect + failover logic
7. Market regime adaptation

---

**Next:** See `IMPROVEMENTS.md` for concrete solutions.
