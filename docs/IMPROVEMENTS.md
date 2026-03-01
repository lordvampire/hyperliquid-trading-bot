> ⚠️ **ARCHIVED — Historical Planning Document**
> 
> This document described the planned improvements from v1 (funding-rate heuristic) to v2 (multi-signal framework).
> The production bot was instead built as the **VMR (Volatility Mean Reversion)** strategy.
> Many of the improvements described here informed VMR's design (adaptive signals, dynamic risk).
> 
> **Current documentation:** See [README.md](../README.md), [README_VMR.md](../README_VMR.md), [USER_MANUAL.md](../USER_MANUAL.md).

---

# Bot Improvements: v1 → v2 Roadmap (ARCHIVED)

**Status:** Planning Phase (archived — superseded by VMR strategy)  
**Target Release:** 2026-Q1  
**Priority:** Multi-Signal + Risk Overhaul + Stress-Testing

---

## Vision: From Heuristic to Engineered

**v1:** Funding-rate heuristic with tight SL/TP  
**v2:** Multi-signal framework with dynamic risk + stress-validated

---

## Tier 1: Critical (MUST-HAVE) 🔴

### 1.1 Multi-Signal Framework
Replace single funding-rate signal with composite scoring.

**Components:**
- **Volatility-Regime Detector** (40% weight)
  - ATR (20-period rolling)
  - Bollinger Band width
  - Historical volatility
  - → Classify: Low/Medium/High regime
  
- **Price-Momentum Detector** (30% weight)
  - RSI (14-period, overbought/oversold)
  - MACD (fast-slow-signal)
  - Rate of Change
  - → Signal: Strong-UP / Neutral / Strong-DOWN
  
- **Order-Book Imbalance** (20% weight)
  - Bid/Ask ratio at $1M depth
  - Limit order book skew
  - → Signal: Directional pressure
  
- **Funding-Rate Signal** (10% weight, downgraded!)
  - 24h trend + current level + volatility
  - Only confirms, doesn't lead
  - → Signal: Supportive/Neutral/Opposing

**Combination Logic:**
```
Combined_Score = 0.40*Vol + 0.30*Momentum + 0.20*OBImbalance + 0.10*Funding
Signal_Threshold = 0.35 (was 0.30)
Confidence = abs(Combined_Score)
```

**Expected Impact:**
- Less overtraded signal
- More robust across market regimes
- Higher signal quality → can raise thresholds again

---

### 1.2 Dynamic Risk Sizing
Replace static 5% SL/TP + 2% position.

**Components:**
- **Volatility-Scaled Stop-Loss**
  ```
  SL_pct = ATR(20) / Close * 2.0  # Typically 2-4% based on volatility
  TP_pct = SL_pct * 2.5           # 1:2.5 Risk:Reward minimum
  ```
  - High vol: 3-4% SL, 7.5-10% TP
  - Low vol: 1.5-2% SL, 3.75-5% TP

- **Position Sizing = f(Volatility, Correlation, Equity)**
  ```
  Base_Risk = Account_Equity * 1.5%  # Risk capital per trade
  Vol_Factor = 20 / ATR(20)          # Inverse vol scaling
  Corr_Factor = 1 / sqrt(N_OpenPos)  # Reduce if many correlated positions
  
  Position_Size = Base_Risk / SL_pct * Vol_Factor * Corr_Factor
  ```
  - Low vol/low correlation: up to 3% position
  - High vol/high correlation: down to 0.5% position

- **Funding P&L in Position Life**
  ```
  Exit Decision:
    IF TP_Hit OR SL_Hit:
      Close immediately
    ELIF Funding_Accumulated > Risk_Per_Trade * 0.5:
      Close early (protect profits)
    ELIF Opposite_Signal:
      Reverse or close (regime change)
  ```

**Expected Impact:**
- Win-rate may drop slightly (tighter stops)
- P&L per trade increases significantly (better R:R)
- Overall Sharpe ratio improves

---

### 1.3 Statistical Validation Framework
Prove the system actually has edge.

**Metrics to Track:**
- **Win-Rate %**: Must be >55% minimum, ideally >60%
- **Payoff-Ratio**: Avg Win / Avg Loss (target: 1.5+)
- **Sharpe Ratio**: Risk-adjusted returns (target: >1.0)
- **Max Drawdown**: Peak-to-trough (target: <15%)
- **Profit Factor**: Total Wins / Total Losses (target: 1.8+)
- **Average Hold Time**: How long before exit
- **Slippage + Fees Impact**: Actual vs ideal

**Logging:**
- Every signal → SQLite
- Every execution → filled price, actual SL/TP, hold time
- Every close → actual P&L, funding paid, fees
- Daily summary → CSV export

**Reporting:**
- Backtest → CSV + PDF summary
- Testnet → HTML report with graphs
- Mainnet → Real-time dashboard

**Threshold for Live:**
```
Must have BOTH:
1. Backtest: Win-Rate >60%, Sharpe >0.8, Max-DD <15% over 3-month period
2. Testnet: 7+ days, 100+ signals, consistent >55% win-rate
3. Stats significance: Chi-square test p<0.05 for win-rate vs baseline (50%)
```

**Expected Impact:**
- Remove guesswork
- Prove edge or discover it's negative
- Measure improvements objectively

---

## Tier 2: Important (SHOULD-HAVE) 🟡

### 2.1 Stress-Test Framework
Validate system against edge-cases.

**Scenarios:**

1. **Crash Scenario**
   - Simulate 10% down in 5 minutes
   - Check: Does SL trigger? How fast? Slippage?
   
2. **Funding Spike**
   - Simulate +200% funding rate spike
   - Check: How much P&L drained? Position still viable?
   
3. **API Disconnect**
   - Simulate 5-minute connection loss
   - Check: Can system recover? Position state? Emergency close?
   
4. **Black Swan**
   - Simulate 30% crash + volatility spike
   - Check: Cascading liquidation risk? Portfolio collapse?

**Output:**
- For each scenario: System survives? How?
- Worst-case P&L impact
- Recommendations for stops/exits

**Expected Impact:**
- Identify failure modes before they happen
- Build confidence in failover logic
- Reduce live trading surprises

---

### 2.2 Market Regime Adaptation
Adjust strategy parameters based on market conditions.

**Regime Classification:**
```
IF ATR(20) < Percentile(ATR, 25):  Regime = "LOW_VOL"
IF ATR(20) > Percentile(ATR, 75):  Regime = "HIGH_VOL"
ELSE: Regime = "NORMAL"

IF Price_Trend > 0.3 * ATR:        Trend = "STRONG_UP"
IF Price_Trend < -0.3 * ATR:       Trend = "STRONG_DOWN"
ELSE: Trend = "SIDEWAYS"
```

**Parameter Adjustments:**
```
LOW_VOL + SIDEWAYS:
  → Mean-reversion bias
  → Position size: +50%
  → TP: closer (3%)
  → SL: wider (5%)

HIGH_VOL + STRONG_TREND:
  → Momentum bias
  → Position size: -30%
  → TP: wider (8%)
  → SL: tighter (2%)

NORMAL:
  → Default parameters
```

**Expected Impact:**
- Higher win-rate in range markets
- Better P&L in trending markets
- Reduced drawdowns in volatility spikes

---

### 2.3 Reconnect + Failover Logic
Handle API failures gracefully.

**Components:**
- **Backup Endpoints**: Secondary API route
- **Position Tracking**: Log all fills to disk before closing
- **Heartbeat Monitor**: Check connection every 10 seconds
- **Emergency Close**: If disconnect >5min, close all positions at market

**Implementation:**
```python
# exchange.py additions:
class ResilientExchange:
    def __init__(self, primary_url, backup_url):
        self.primary = primary_url
        self.backup = backup_url
        self.last_heartbeat = time.time()
    
    def execute_with_failover(self, order):
        try:
            return self.primary.place_order(order)
        except ConnectionError:
            logger.warning("Primary disconnected, trying backup...")
            return self.backup.place_order(order)
    
    def heartbeat_monitor(self):
        while True:
            if time.time() - self.last_heartbeat > 300:  # 5 min
                logger.critical("Heartbeat timeout! Emergency close all.")
                self.emergency_close_all()
            time.sleep(10)
```

**Expected Impact:**
- Fewer "orphaned positions"
- Faster recovery from network issues
- Better operational stability

---

### 2.4 Extended Testnet (7+ days)
Run with realistic signal frequency.

**Setup:**
- Deploy to testnet runner
- Let it run 7+ days
- Collect 100+ signals minimum
- Output statistics

**Metrics:**
- Consistency of win-rate across days
- Largest single drawdown
- Total Sharpe ratio
- Funding impact analysis

**Pass Criteria:**
```
Win-Rate: >55% (ideally 60%+)
Max Single Drawdown: <10%
Days with Positive P&L: >80%
Sharpe: >0.5 (conservative)
```

**Expected Impact:**
- Statistically valid sample size
- Confidence in system before live
- Identify day-of-week effects

---

## Tier 3: Nice-to-Have (COULD-HAVE) 🟢

### 3.1 Funding-Rate Arbitrage Module
Separate carry-trade from directional trades.

**Concept:**
- Long Spot (hold physical) + Short Perp (35x) = collect funding
- No directional risk
- Pure carry income

**Not implemented in v1, optional for v2.**

---

### 3.2 Advanced Visualizations
Dashboard to monitor system health.

**Features:**
- Real-time P&L curve
- Signal heatmap (BTC, ETH, SOL)
- Drawdown depth gauge
- Win-rate rolling statistics
- Funding accumulated chart

**Stack:** Streamlit or Grafana

---

## Implementation Priority

```
PHASE 1 (Weeks 1-2):
├─ Multi-Signal Framework
├─ Dynamic Risk Sizing
└─ Statistical Validation

PHASE 2 (Weeks 2-3):
├─ Stress-Test Framework
├─ Reconnect + Failover
└─ Extended Testnet (7+ days)

PHASE 3 (Weeks 3-4):
├─ Market Regime Adaptation
└─ Final stress-testing

PHASE 4 (Week 4+):
├─ Mainnet with $500 (small)
├─ 24/7 monitoring
└─ Scaling if profitable
```

---

## Success Criteria for v2

✅ Multi-signal framework reduces overtrading  
✅ Dynamic SL/TP improves Sharpe ratio  
✅ Statistical proof of >55% win-rate  
✅ Stress tests pass (no catastrophic failures)  
✅ 7-day testnet run shows consistency  
✅ Reconnect logic handles API failures  
✅ Mainnet with $500 → 30+ days → 2-5% ROI minimum

---

## Next Steps

1. **Design Phase**: Finalize signal weights, thresholds, regime definitions
2. **Development**: Build modules one at a time (Phase 1 first)
3. **Testing**: Backtest each module independently, then combined
4. **Deployment**: Move to testnet, then mainnet

See `ROADMAP.md` for detailed timeline.
