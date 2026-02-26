# Implementation Roadmap: v2 Multi-Signal Bot

**Status:** Planning  
**Estimated Duration:** 4 weeks  
**Target Launch:** 2026-03-26 (Mainnet)  
**Team:** Clara (Orchestration) + 6 Agents (Dev, QA, Research)

---

## Architecture v1 → v2

```
v1 (Current):
├─ Funding-Rate Signal (Heuristic 30%)
├─ Static Risk (5% SL/TP, 2% position)
└─ Basic Testnet Validation

v2 (Target):
├─ Multi-Signal (Vol 40% + Momentum 30% + OB 20% + Funding 10%)
├─ Dynamic Risk (Vol-scaled SL/TP, Correlation-adjusted position)
├─ Stress-Tested Framework
├─ Statistical Validation
├─ Reconnect + Failover Logic
└─ Extended 7-day Testnet with stats
```

---

## Phase 1: Multi-Signal + Dynamic Risk (Weeks 1-2)

### Week 1: Signal Layers

#### Task 1.1: Volatility-Regime Detector
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `signals/volatility_regime.py` 
  - ATR(20) calculation
  - Bollinger Band width
  - Historical vol percentile
  - Regime classification (Low/Med/High)
- [ ] Unit tests (test_vol_regime.py)
- [ ] Integration with main signal pipeline

**Definition of Done:**
- Code deployed to v2/ directory
- Tests passing (100% coverage)
- Commit + PR to main

**Dependencies:** None  
**Est. Hours:** 4h

---

#### Task 1.2: Price-Momentum Detector
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `signals/price_momentum.py`
  - RSI(14) calculation
  - MACD + signal line
  - Rate of Change (ROC)
  - Signal classification (Strong-UP/Neutral/Strong-DOWN)
- [ ] Unit tests (test_price_momentum.py)
- [ ] Real-time candle feeding

**Definition of Done:**
- Code deployed
- Tests passing
- Commit + PR

**Dependencies:** Needs OHLCV data from exchange.py  
**Est. Hours:** 4h

---

#### Task 1.3: Order-Book Imbalance Detector
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `signals/orderbook_imbalance.py`
  - Fetch order book ($1M depth)
  - Calculate bid/ask ratio
  - Limit order skew analysis
  - Signal classification (Long-bias/Neutral/Short-bias)
- [ ] Caching (avoid API spam)
- [ ] Unit tests

**Definition of Done:**
- Code deployed
- Tests passing
- API call throttling verified

**Dependencies:** Hyperliquid OB API  
**Est. Hours:** 5h

---

#### Task 1.4: Composite Signal Combiner
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `signals/combined_signal.py`
  - Weighted combination: 40% Vol + 30% Mom + 20% OB + 10% Funding
  - Confidence calculation
  - Signal output (BUY/SELL/HOLD)
- [ ] Threshold logic (0.35 minimum)
- [ ] Logging + statistics

**Definition of Done:**
- Code deployed
- Weighted formula verified
- Integration tests with all 4 signal sources

**Dependencies:** All 4 signal detectors (1.1-1.3)  
**Est. Hours:** 3h

---

### Week 2: Risk Overhaul + Statistics

#### Task 2.1: Dynamic Risk Sizing Engine
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `risk/dynamic_sizing.py`
  - Volatility-scaled SL% calculation
  - 1:2.5 R:R enforcement
  - Position size = f(Vol, Corr, Equity)
  - Correlation detection (parallel positions)
- [ ] Integration with manager.py
- [ ] Unit tests

**Definition of Done:**
- Code deployed
- Stress tests pass (position sizes reasonable)
- Logging shows all calculations

**Dependencies:** volatility_regime.py (Task 1.1)  
**Est. Hours:** 5h

---

#### Task 2.2: Statistical Validation Framework
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `monitoring/statistik.py`
  - Track every signal: timestamp, symbol, confidence, direction
  - Track every execution: entry price, SL, TP, hold duration
  - Track every close: actual P&L, fees paid, funding accumulated
  - Calculate metrics: Win-Rate, Sharpe, Max-DD, Payoff-Ratio, Profit-Factor
- [ ] SQLite schema updates (new columns for tracking)
- [ ] CSV export functionality

**Metrics Tracked:**
```
Per-Trade:
  - win/loss (binary)
  - P&L absolute
  - P&L % of capital
  - Hold time (minutes)
  - Fees paid
  - Funding accumulated
  - SL triggered vs TP triggered

Rolling (daily/weekly):
  - Win-rate %
  - Sharpe ratio
  - Max drawdown
  - Payoff ratio (Avg-Win / Avg-Loss)
  - Profit factor (Total-Win / Total-Loss)
```

**Definition of Done:**
- Code deployed
- SQLite tracking verified
- CSV exports working
- Backtest now outputs full statistics

**Dependencies:** strategy_b.py (modified to log metadata)  
**Est. Hours:** 6h

---

#### Task 2.3: Statistics Reporting + Thresholds
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `monitoring/report_generator.py`
  - HTML report generation
  - Charts: P&L curve, win-rate over time, drawdown depth, Sharpe rolling
  - Threshold checks: Win-Rate >55%? Sharpe >0.5? Max-DD <15%?
  - Pass/Fail verdict for live deployment
- [ ] CSV summaries
- [ ] Logging all metrics

**Report Output:**
```
📊 BACKTEST REPORT: BTC Strategy v2
──────────────────────────────────
Period: 2026-02-26 to 2026-03-26
Trades: 127
Win-Rate: 58.3% ✅ (>55% required)
Sharpe: 0.87 ✅ (>0.5 required)
Max-DD: 8.2% ✅ (<15% required)
Payoff-Ratio: 1.6 ✅ (>1.5 required)
Profit-Factor: 2.1 ✅ (>1.8 required)

VERDICT: ✅ READY FOR TESTNET
```

**Definition of Done:**
- Reports generated for backtest
- Thresholds defined + coded
- Pass/Fail logic working

**Dependencies:** statistik.py (Task 2.2)  
**Est. Hours:** 4h

---

## Phase 2: Resilience + Extended Testing (Weeks 2-3)

### Task 3.1: Stress-Test Framework
**Assigned to:** QA Agent  
**Subtasks:**
- [ ] `risk/stress_tester.py`
  - Scenario 1: 10% crash in 5 min → log SL triggers + slippage
  - Scenario 2: Funding +200% → calculate P&L drain
  - Scenario 3: 5-min API disconnect → position survival check
  - Scenario 4: 30% crash + vol spike → liquidation risk?
- [ ] Scenario library (pluggable)
- [ ] Report generation per scenario

**Output Example:**
```
🚨 STRESS TEST RESULTS
──────────────────────
Crash (10% / 5min): ✅ SL triggered normally, no cascade
Funding Spike: ⚠️ 2.3% P&L drain, position viable
API Disconnect: ✅ Emergency close executed
Black Swan: ⚠️ 15% temporary loss, recovered in 20min

VERDICT: ✅ SYSTEM RESILIENT
```

**Definition of Done:**
- All 4 scenarios tested
- Report generated
- System passes stress tests

**Dependencies:** Dynamic risk sizing (Task 2.1)  
**Est. Hours:** 6h

---

### Task 3.2: Reconnect + Failover Logic
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `monitoring/reconnect.py`
  - Backup API endpoint configuration
  - Heartbeat monitor (check every 10 sec)
  - Position tracking (log all fills to disk)
  - Emergency close trigger (if disconnect >5 min)
- [ ] Test failover simulation
- [ ] Error handling + logging

**Definition of Done:**
- Failover code deployed
- Disconnect simulation passes
- Position recovery verified
- No orphaned positions

**Dependencies:** exchange.py (modified for backup endpoints)  
**Est. Hours:** 5h

---

### Task 3.3: Extended Testnet Runner (7+ days)
**Assigned to:** QA Agent  
**Subtasks:**
- [ ] Deploy v2 code to Hyperliquid Testnet
- [ ] Run for 7+ consecutive days
- [ ] Collect 100+ signals minimum
- [ ] Generate daily statistics
- [ ] Final report with pass/fail criteria

**Acceptance Criteria:**
```
Win-Rate: >55% ✅
Max Single DD: <10% ✅
Positive P&L Days: >80% ✅
Sharpe: >0.5 ✅
Consistency: Similar stats across all 7 days
```

**Duration:** 7 calendar days  
**Est. Prep Hours:** 2h

---

## Phase 3: Tuning + Adaptation (Weeks 3-4)

### Task 4.1: Market Regime Adaptation
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] `risk/regime_detector.py`
  - Classify current market: Low-Vol/Normal/High-Vol
  - Classify trend: Strong-UP/Sideways/Strong-DOWN
  - Adjust parameters per regime (TP%, position size, signal threshold)
- [ ] A/B test: regime-adapted vs non-adapted
- [ ] Logging of regime switches

**Example Adjustments:**
```
If Low-Vol + Sideways:
  - Mean-reversion bias: +30% weight to reversal signals
  - Position size: +50%
  - TP: 3% (tighter)
  - SL: 5% (wider)

If High-Vol + Strong-Trend:
  - Momentum bias: +30% weight to trend signals
  - Position size: -30%
  - TP: 8% (wider)
  - SL: 2% (tighter)
```

**Definition of Done:**
- Code deployed
- Backtesting shows improvement
- Testnet validation running

**Dependencies:** volatility_regime.py + price_momentum.py  
**Est. Hours:** 6h

---

### Task 4.2: Final Optimization & Testing
**Assigned to:** QA Agent  
**Subtasks:**
- [ ] Backtest v2 full system (multi-signal + dynamic risk + regime)
- [ ] Compare vs v1 (better Sharpe? Lower DD? Higher Win-Rate?)
- [ ] Edge-case testing (gaps in OHLCV data, missing funding data, etc.)
- [ ] Final stress test with v2 parameters
- [ ] Generate final go/no-go report

**Comparison Matrix:**
```
Metric          | v1     | v2     | Improvement
──────────────────────────────────────────
Win-Rate        | 45%    | 58%    | +13pp ✅
Sharpe          | 0.3    | 0.87   | +190% ✅
Max-DD          | 18%    | 8.2%   | -55% ✅
Payoff-Ratio    | 0.9    | 1.6    | +78% ✅
```

**Definition of Done:**
- Full comparison report
- GO/NO-GO verdict
- Mainnet readiness signed off

**Dependencies:** All Phase 1-3 tasks  
**Est. Hours:** 4h

---

## Phase 4: Mainnet Deployment (Week 4+)

### Task 5.1: Mainnet Configuration & Dry-Run
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] Configure mainnet keys (DO NOT COMMIT!)
- [ ] Dry-run with $500 capital (small stake)
- [ ] Monitor 24/7 for first 7 days
- [ ] Daily reports: P&L, signals, trades, stats
- [ ] Emergency stop procedures documented

**Capital:** $500 USDC (small)  
**Expected P&L:** 1-5% per month (conservative)  
**Risk Tolerance:** Max 15% monthly loss → stop trading

**Definition of Done:**
- Mainnet running stable
- 7+ days of live data collected
- Consistent with testnet stats
- No catastrophic failures

**Duration:** 7 calendar days (minimum)  
**Est. Hours:** 2h setup + monitoring

---

### Task 5.2: Monitoring Dashboard
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] Real-time P&L curve
- [ ] Signal heatmap (BTC, ETH, SOL)
- [ ] Drawdown gauge
- [ ] Win-rate rolling stats
- [ ] Alerts: >2% daily loss, >5 consecutive losses, API issues

**Stack:** Streamlit (Python dashboard)

**Definition of Done:**
- Dashboard accessible (local or cloud)
- Real-time updates every 1 minute
- All KPIs visible at a glance

**Est. Hours:** 4h

---

### Task 5.3: Scaling & Optimization
**Assigned to:** Dev Agent  
**Subtasks:**
- [ ] If mainnet +2% ROI after 30 days: increase capital to $2k
- [ ] If mainnet +5% ROI after 30 days: increase capital to $5k
- [ ] Monitor correlation between BTC/ETH/SOL, adjust position sizes
- [ ] Analyze signal quality, refine thresholds if needed

**Scaling Criteria:**
```
ROI<0%:   STOP trading, investigate
ROI 0-2%: MAINTAIN $500, tighten risk
ROI 2-5%: INCREASE to $2k after 30 days
ROI >5%:  INCREASE to $5k, consider more symbols
```

**Duration:** Ongoing  
**Est. Hours:** 2h per week monitoring

---

## GitHub Structure (v2)

```
hyperliquid-trading-bot/
├── v2/
│  ├── signals/
│  │  ├─ __init__.py
│  │  ├─ volatility_regime.py       [Task 1.1]
│  │  ├─ price_momentum.py          [Task 1.2]
│  │  ├─ orderbook_imbalance.py     [Task 1.3]
│  │  └─ combined_signal.py         [Task 1.4]
│  ├── risk/
│  │  ├─ __init__.py
│  │  ├─ dynamic_sizing.py          [Task 2.1]
│  │  ├─ regime_detector.py         [Task 4.1]
│  │  └─ stress_tester.py           [Task 3.1]
│  ├── monitoring/
│  │  ├─ __init__.py
│  │  ├─ statistik.py               [Task 2.2]
│  │  ├─ report_generator.py        [Task 2.3]
│  │  ├─ reconnect.py               [Task 3.2]
│  │  └─ dashboard.py               [Task 5.2]
│  ├── tests/
│  │  ├─ test_volatility_regime.py
│  │  ├─ test_price_momentum.py
│  │  ├─ test_orderbook_imbalance.py
│  │  ├─ test_combined_signal.py
│  │  ├─ test_dynamic_sizing.py
│  │  ├─ test_statistical_validation.py
│  │  └─ test_stress_scenarios.py
│  ├── backtest_v2.py               [Enhanced: uses dynamic risk + multi-signal]
│  ├── testnet_runner_v2.py         [Enhanced: collects statistics]
│  ├── main_v2.py                   [Entry point]
│  └─ strategy_b_v2.py              [Updated: uses combined signal]
├── docs/
│  ├─ PERPLEXITY_ANALYSIS.md        [This analysis]
│  ├─ IMPROVEMENTS.md               [Improvement roadmap]
│  └─ ROADMAP.md                    [This file]
└── v1/                              [Keep for reference]
```

---

## Timeline Summary

| Phase | Week | Milestones | Status |
|-------|------|-----------|--------|
| 1 | 1-2 | Multi-signal + Dynamic Risk | ⏳ Pending |
| 2 | 2-3 | Stress Tests + Extended Testnet | ⏳ Pending |
| 3 | 3-4 | Regime Adaptation + Optimization | ⏳ Pending |
| 4 | 4+ | Mainnet Deployment | ⏳ Pending |

**Total Estimated Effort:** ~60 development hours + 7 days testnet + 7 days mainnet  
**Expected Completion:** 2026-03-26

---

## Success Criteria (Go/No-Go)

### For Mainnet Deployment:
- ✅ Backtest: Win-Rate >60%, Sharpe >0.8, Max-DD <15%
- ✅ Testnet (7-days): Win-Rate >55%, consistency across days
- ✅ Stress tests: All scenarios pass (no cascading failures)
- ✅ Statistics: Proof of edge (p<0.05 for win-rate)
- ✅ Reconnect logic: Tested and verified
- ✅ Initial mainnet ($500): No catastrophic losses in first 7 days

### For Scaling Beyond $500:
- ✅ Mainnet 30-days: Consistent positive ROI
- ✅ Correlation monitoring: No systemic drawdown
- ✅ Signal quality: Win-rate maintained above >55%

---

## Agent Assignments

| Agent | Primary Role | Tasks |
|-------|------|-------|
| Dev | Code Implementation | 1.1-1.4, 2.1-2.3, 3.2, 4.1, 5.1-5.3 |
| QA | Testing + Validation | 3.1, 3.3, 4.2, Backtest |
| Research | Analysis + Optimization | Signal tuning, threshold optimization |
| Planner | Timeline + Coordination | Already done (this roadmap) |
| (Clara) | Orchestration | Spawn agents, coordinate phases, final signoff |

---

## Notes

- **Security:** Mainnet keys stored in secure `.env`, NEVER committed
- **Backup:** Daily backups of testnet runs + reports
- **Monitoring:** 24/7 during mainnet phase
- **Rollback:** Keep v1 operational as fallback
- **Communication:** Daily standup + weekly reviews

---

**Next Action:** Push all docs to GitHub, then begin Phase 1 (Spawn Dev Agent for Task 1.1).

