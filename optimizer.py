#!/usr/bin/env python3
"""
optimizer.py — VMR Strategy Parameter Optimizer
================================================
Standalone grid-search optimizer for the Volatility Mean Reversion strategy.

Workflow:
    1. fetch_180d_candles(symbol)  → pulls 1h OHLCV from Hyperliquid (mainnet),
                                     caches to candle_cache/<symbol>_180d.csv
    2. validate_data(df, symbol)   → checks for gaps, anomalies, quality stats
    3. run_grid_search(symbol)     → tests all param combinations via
                                     VMRStrategy.run_backtest()
    4. Results saved to:
         optimization_results_<SYMBOL>_<DATE>.csv
         optimization_summary.md  (top-20 per symbol + overall top-10)

Parameter grid (~10,000 combinations total):
    spike_threshold_pct : [0.5, 0.75, 1.0, 1.25, 1.5]
    bb_std_multiplier   : [1.0, 1.5, 2.0, 2.5, 3.0]
    sl_pct              : [0.003, 0.004, 0.005, 0.006, 0.007]
    tp_pct              : [0.010, 0.012, 0.015, 0.020, 0.025]
    position_size_pct   : [0.005, 0.01, 0.015, 0.02]
    max_hold_hours      : [12, 24, 36, 48]

Usage:
    python optimizer.py                      # BTC, ETH, SOL full run
    python optimizer.py --symbol BTC         # single symbol
    python optimizer.py --symbol BTC --workers 8
    python optimizer.py --dry-run            # quick smoke-test (50 combos)
    python optimizer.py --no-cache           # re-fetch even if cache exists
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import logging
import math
import multiprocessing
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

# ── Make sure we can import strategy_engine even when run from a subdir ──────
sys.path.insert(0, str(Path(__file__).parent))
from strategy_engine import VMRConfig, VMRStrategy

# ============================================================================
# LOGGING
# ============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("optimizer.log"),
    ],
)
logger = logging.getLogger("optimizer")


# ============================================================================
# CONSTANTS / DIRECTORIES
# ============================================================================

REPO_ROOT   = Path(__file__).parent
CACHE_DIR   = REPO_ROOT / "candle_cache"
RESULTS_DIR = REPO_ROOT / "optimization_results"

CACHE_DIR.mkdir(exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

CANDLE_DAYS   = 180          # days of 1h candles to fetch
CANDLE_HOURS  = CANDLE_DAYS * 24   # expected bar count
SYMBOLS       = ["BTC", "ETH", "SOL"]
TODAY_STR     = datetime.now().strftime("%Y-%m-%d")

# Best-params store — written after each symbol run, read by bot commands
BEST_PARAMS_FILE = REPO_ROOT / "best_params.json"


# ============================================================================
# PARAMETER GRID
# ============================================================================

PARAM_GRID: Dict[str, List[Any]] = {
    "spike_threshold_pct": [0.5, 0.75, 1.0, 1.25, 1.5],
    "bb_std_multiplier":   [1.0, 1.5,  2.0, 2.5,  3.0],
    "sl_pct":              [0.003, 0.004, 0.005, 0.006, 0.007],
    "tp_pct":              [0.010, 0.012, 0.015, 0.020, 0.025],
    "position_size_pct":   [0.005, 0.01,  0.015, 0.02],
    "max_hold_hours":      [12,    24,    36,    48],
}

TOTAL_COMBOS = 1
for _v in PARAM_GRID.values():
    TOTAL_COMBOS *= len(_v)


# ============================================================================
# DATA FETCHER (180d)
# ============================================================================

def fetch_180d_candles(
    symbol: str,
    use_cache: bool = True,
    cache_max_age_hours: int = 6,
) -> Optional[pd.DataFrame]:
    """
    Fetch 180 days of 1h OHLCV candles from Hyperliquid mainnet API.

    Caches result to candle_cache/<SYMBOL>_180d.csv.
    Re-fetches if cache is older than `cache_max_age_hours`.

    Args:
        symbol:              Instrument name ("BTC", "ETH", "SOL").
        use_cache:           If False, always re-fetch from API.
        cache_max_age_hours: Maximum age of cached file in hours before refresh.

    Returns:
        DataFrame[timestamp, open, high, low, close, volume] sorted asc,
        or None on failure.
    """
    cache_file = CACHE_DIR / f"{symbol}_180d.csv"

    # ── Try cache first ──────────────────────────────────────────────────────
    if use_cache and cache_file.exists():
        age_hours = (time.time() - cache_file.stat().st_mtime) / 3600
        if age_hours < cache_max_age_hours:
            logger.info(
                f"[{symbol}] Loading from cache ({age_hours:.1f}h old): {cache_file}"
            )
            try:
                df = pd.read_csv(cache_file, parse_dates=["timestamp"])
                df = df.sort_values("timestamp").reset_index(drop=True)
                logger.info(f"[{symbol}] Cache hit: {len(df)} bars")
                return df
            except Exception as exc:
                logger.warning(f"[{symbol}] Cache read failed ({exc}), re-fetching …")

    # ── Fetch from API ───────────────────────────────────────────────────────
    try:
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        info = Info(constants.MAINNET_API_URL, skip_ws=True)

        end_ms   = int(datetime.now().timestamp() * 1000)
        start_ms = end_ms - (CANDLE_DAYS * 24 * 3_600_000)

        logger.info(
            f"[{symbol}] Fetching {CANDLE_DAYS}d 1h candles from Hyperliquid …"
        )

        # Hyperliquid may cap single requests; fetch in 30d chunks to be safe
        all_raw: List[Dict] = []
        chunk_ms = 30 * 24 * 3_600_000   # 30 days per request

        chunk_start = start_ms
        while chunk_start < end_ms:
            chunk_end = min(chunk_start + chunk_ms, end_ms)
            raw = info.candles_snapshot(
                name=symbol,
                interval="1h",
                startTime=chunk_start,
                endTime=chunk_end,
            )
            if raw:
                all_raw.extend(raw)
            chunk_start = chunk_end
            time.sleep(0.2)   # polite rate-limit pause

        if not all_raw:
            logger.error(f"[{symbol}] API returned no candles")
            return None

        rows = []
        seen_ts: set = set()
        for c in all_raw:
            ts = int(c["t"])
            if ts in seen_ts:
                continue
            seen_ts.add(ts)
            rows.append({
                "timestamp": ts,
                "open":   float(c["o"]),
                "high":   float(c["h"]),
                "low":    float(c["l"]),
                "close":  float(c["c"]),
                "volume": float(c["v"]),
            })

        df = pd.DataFrame(rows)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms")
        df = df.sort_values("timestamp").reset_index(drop=True)

        # Save to cache
        df.to_csv(cache_file, index=False)
        logger.info(
            f"[{symbol}] Fetched {len(df)} bars → cached to {cache_file}"
        )
        return df

    except Exception as exc:
        logger.error(f"[{symbol}] Fetch failed: {exc}")
        return None


# ============================================================================
# DATA QUALITY VALIDATION
# ============================================================================

def validate_data(df: pd.DataFrame, symbol: str) -> Dict[str, Any]:
    """
    Validate candle data quality and log statistics.

    Checks:
    • Coverage vs expected 180d window
    • Missing/duplicate timestamps
    • OHLCV anomalies (zero prices, negative volume, H < L)
    • Large gaps (> 2 consecutive hours missing)

    Args:
        df:     OHLCV DataFrame (sorted ascending).
        symbol: Symbol label for logging.

    Returns:
        Dict with quality_ok (bool) and detailed stats.
    """
    stats: Dict[str, Any] = {
        "symbol":           symbol,
        "total_bars":       len(df),
        "expected_bars":    CANDLE_HOURS,
        "coverage_pct":     round(len(df) / CANDLE_HOURS * 100, 2),
        "date_from":        str(df["timestamp"].iloc[0]),
        "date_to":          str(df["timestamp"].iloc[-1]),
        "quality_ok":       True,
        "warnings":         [],
    }

    issues: List[str] = []

    # Coverage
    if stats["coverage_pct"] < 90:
        issues.append(
            f"Low coverage {stats['coverage_pct']:.1f}% "
            f"({len(df)}/{CANDLE_HOURS} expected bars)"
        )

    # Duplicate timestamps
    dupes = df["timestamp"].duplicated().sum()
    stats["duplicate_bars"] = int(dupes)
    if dupes > 0:
        issues.append(f"{dupes} duplicate timestamps")

    # Zero / NaN prices
    zero_close = (df["close"] <= 0).sum()
    nan_rows   = df[["open","high","low","close","volume"]].isna().any(axis=1).sum()
    stats["zero_close_bars"] = int(zero_close)
    stats["nan_rows"]        = int(nan_rows)
    if zero_close > 0:
        issues.append(f"{zero_close} zero/negative close prices")
    if nan_rows > 0:
        issues.append(f"{nan_rows} rows with NaN values")

    # OHLC sanity (H >= L)
    bad_hl = (df["high"] < df["low"]).sum()
    stats["bad_hl_bars"] = int(bad_hl)
    if bad_hl > 0:
        issues.append(f"{bad_hl} bars with high < low")

    # Gap detection
    if len(df) > 1:
        time_diffs = df["timestamp"].diff().dropna()
        expected_delta = pd.Timedelta("1h")
        gaps = time_diffs[time_diffs > expected_delta * 2]
        stats["gap_count"]       = len(gaps)
        stats["max_gap_hours"]   = float(time_diffs.max().total_seconds() / 3600)
        if len(gaps) > 0:
            issues.append(
                f"{len(gaps)} gaps detected (max gap: "
                f"{stats['max_gap_hours']:.1f}h)"
            )
    else:
        stats["gap_count"]     = 0
        stats["max_gap_hours"] = 0.0

    # Return statistics
    df_copy = df.copy()
    df_copy["return_pct"] = df_copy["close"].pct_change() * 100
    stats["mean_return_pct"] = round(float(df_copy["return_pct"].mean()), 4)
    stats["std_return_pct"]  = round(float(df_copy["return_pct"].std()),  4)
    stats["max_return_pct"]  = round(float(df_copy["return_pct"].max()),  4)
    stats["min_return_pct"]  = round(float(df_copy["return_pct"].min()),  4)

    stats["warnings"]  = issues
    stats["quality_ok"] = len(issues) == 0 or (
        stats["coverage_pct"] >= 85
        and stats["zero_close_bars"] == 0
        and stats["nan_rows"] == 0
    )

    # Log
    q_label = "✅ GOOD" if stats["quality_ok"] else "⚠️  ISSUES"
    logger.info(
        f"[{symbol}] Data quality {q_label}: "
        f"{len(df)} bars, coverage={stats['coverage_pct']:.1f}%, "
        f"gaps={stats.get('gap_count',0)}"
    )
    for w in issues:
        logger.warning(f"[{symbol}]   ⚠  {w}")

    return stats


# ============================================================================
# SHARPE CALCULATION
# ============================================================================

def compute_sharpe(stats: Dict[str, Any], days: int = CANDLE_DAYS) -> float:
    """
    Compute annualised Sharpe ratio from backtest stats.

    Uses trade P&L as the return series. Missing-trade bars are filled
    with 0% return. Annualisation factor = sqrt(365 / days * n_trades).

    Falls back to Calmar-like proxy when fewer than 2 trades exist.

    Args:
        stats: Dict returned by VMRStrategy.run_backtest().
        days:  Backtest window in days (for annualisation).

    Returns:
        Sharpe ratio (float). Negative values indicate poor performance.
    """
    trade_log = stats.get("trade_log", [])
    n_trades  = len(trade_log)

    if n_trades < 2:
        # Simple Calmar proxy: annualised return / drawdown
        ret_pct = stats.get("return_pct", 0.0) / 100
        mdd_pct = stats.get("max_dd_pct", 1.0) / 100
        ann_ret = ret_pct * (365 / days)
        return round(ann_ret / (mdd_pct + 0.001), 4)

    # Per-trade returns as fraction
    trade_returns = [t["pnl_pct"] / 100 for t in trade_log]
    arr = np.array(trade_returns, dtype=float)

    mean_r = arr.mean()
    std_r  = arr.std()

    if std_r < 1e-9:
        return round(mean_r * 10, 4)   # constant returns → arbitrary positive

    # Annualise: assume trades happen uniformly over `days`
    trades_per_year = n_trades * (365 / days)
    sharpe = (mean_r / std_r) * math.sqrt(trades_per_year)
    return round(sharpe, 4)


# ============================================================================
# FAST VECTORIZED BACKTEST (pre-computes features for O(n) speed per combo)
# ============================================================================

def _precompute_features(df: pd.DataFrame, bb_window: int = 20) -> Dict[str, np.ndarray]:
    """
    Pre-compute all candle-level features needed for signal detection.

    This is called ONCE per symbol. Each combo evaluation then uses
    numpy array indexing instead of re-running pandas operations.

    Returns dict of numpy arrays (all same length as df).
    """
    close  = df["close"].values.astype(float)
    high   = df["high"].values.astype(float)  if "high"  in df.columns else close.copy()
    low    = df["low"].values.astype(float)   if "low"   in df.columns else close.copy()

    n = len(close)

    # 1h return %
    returns = np.zeros(n)
    returns[1:] = (close[1:] - close[:-1]) / close[:-1] * 100

    # Rolling mean and std of close (for BB) — fully vectorised via stride tricks
    from numpy.lib.stride_tricks import sliding_window_view
    rolling_mean = np.full(n, np.nan)
    rolling_std  = np.full(n, np.nan)
    if n >= bb_window:
        windows = sliding_window_view(close, bb_window)   # shape (n-bb_window+1, bb_window)
        rolling_mean[bb_window - 1:] = windows.mean(axis=1)
        rolling_std[bb_window - 1:]  = windows.std(axis=1)

    return {
        "close":        close,
        "high":         high,
        "low":          low,
        "returns":      returns,
        "rolling_mean": rolling_mean,
        "rolling_std":  rolling_std,
        "n":            n,
        "bb_window":    bb_window,
    }


def _fast_backtest(
    feats: Dict[str, np.ndarray],
    params: Dict[str, Any],
    starting_balance: float = 1000.0,
) -> Dict[str, Any]:
    """
    Vectorised bar-by-bar backtest using pre-computed features.

    ~10-50x faster than VMRStrategy.run_backtest() because:
    • Features are pre-computed once for all combos
    • Pure numpy indexing — no pandas inside the hot loop
    • Only iterates over signal bars (not all bars)

    Returns the same dict structure as VMRStrategy.run_backtest().
    """
    spike_threshold = float(params["spike_threshold_pct"])
    bb_mult         = float(params["bb_std_multiplier"])
    sl_pct          = float(params["sl_pct"])
    tp_pct          = float(params["tp_pct"])
    pos_size_pct    = float(params["position_size_pct"])
    max_hold        = int(params["max_hold_hours"])

    close   = feats["close"]
    high    = feats["high"]
    low     = feats["low"]
    ret     = feats["returns"]
    rmean   = feats["rolling_mean"]
    rstd    = feats["rolling_std"]
    n       = feats["n"]
    bbw     = feats["bb_window"]

    balance     = starting_balance
    peak        = starting_balance
    max_dd      = 0.0
    trades: List[Dict] = []
    signals_detected = 0

    # Position state
    in_pos      = False
    pos_dir     = 0       # 1=LONG, -1=SHORT
    entry_price = 0.0
    sl_price    = 0.0
    tp_price    = 0.0
    size_usd    = 0.0
    entry_bar   = 0

    for i in range(bbw, n):
        cp   = close[i]
        hi   = high[i]
        lo   = low[i]
        r    = ret[i]
        rm   = rmean[i]
        rs   = rstd[i]

        if np.isnan(rm) or np.isnan(rs) or rs < 1e-12:
            continue

        bb_upper = rm + bb_mult * rs
        bb_lower = rm - bb_mult * rs

        # ── Check exit ───────────────────────────────────────────────────
        if in_pos:
            bars_held = i - entry_bar
            check_price = cp
            exit_reason = ""

            if pos_dir == 1:    # LONG
                if lo <= sl_price:
                    check_price = sl_price
                    exit_reason = "SL_HIT"
                elif hi >= tp_price:
                    check_price = tp_price
                    exit_reason = "TP_HIT"
                elif bars_held >= max_hold:
                    exit_reason = "MAX_HOLD_EXPIRED"
            else:               # SHORT
                if hi >= sl_price:
                    check_price = sl_price
                    exit_reason = "SL_HIT"
                elif lo <= tp_price:
                    check_price = tp_price
                    exit_reason = "TP_HIT"
                elif bars_held >= max_hold:
                    exit_reason = "MAX_HOLD_EXPIRED"

            if exit_reason:
                if pos_dir == 1:
                    pnl_pct = (check_price - entry_price) / entry_price * 100
                else:
                    pnl_pct = (entry_price - check_price) / entry_price * 100
                pnl_usd = (pnl_pct / 100) * size_usd
                balance += pnl_usd
                trades.append({"pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
                                "exit_reason": exit_reason})
                in_pos = False

                if balance > peak:
                    peak = balance
                dd = (peak - balance) / peak * 100
                if dd > max_dd:
                    max_dd = dd

        # ── Check entry ───────────────────────────────────────────────────
        if not in_pos:
            is_spike = abs(r) >= spike_threshold
            if not is_spike:
                continue

            signals_detected += 1
            raw_dir = 1 if r < -spike_threshold else -1  # mean-revert opposite to spike

            # BB confirmation
            if raw_dir == 1 and cp <= bb_lower:
                direction = 1
            elif raw_dir == -1 and cp >= bb_upper:
                direction = -1
            else:
                continue   # BB not confirmed

            size_usd    = balance * pos_size_pct
            entry_price = cp
            entry_bar   = i

            if direction == 1:   # LONG
                sl_price = cp * (1 - sl_pct)
                tp_price = cp * (1 + tp_pct)
            else:                # SHORT
                sl_price = cp * (1 + sl_pct)
                tp_price = cp * (1 - tp_pct)

            pos_dir = direction
            in_pos  = True

    # Force-close any remaining position
    if in_pos:
        lp = close[-1]
        if pos_dir == 1:
            pnl_pct = (lp - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - lp) / entry_price * 100
        pnl_usd = (pnl_pct / 100) * size_usd
        balance += pnl_usd
        trades.append({"pnl_pct": pnl_pct, "pnl_usd": pnl_usd,
                        "exit_reason": "END_OF_DATA"})

    # ── Stats ─────────────────────────────────────────────────────────────
    wins   = [t for t in trades if t["pnl_usd"] > 0]
    losses = [t for t in trades if t["pnl_usd"] <= 0]
    total_pnl  = sum(t["pnl_usd"] for t in trades)
    gross_p    = sum(t["pnl_usd"] for t in wins)
    gross_l    = abs(sum(t["pnl_usd"] for t in losses))

    return {
        "total_bars":       n,
        "signals_detected": signals_detected,
        "trades":           len(trades),
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(len(wins) / len(trades) * 100, 2) if trades else 0.0,
        "total_pnl_usd":    round(total_pnl, 4),
        "return_pct":       round((balance - starting_balance) / starting_balance * 100, 4),
        "max_dd_pct":       round(max_dd, 4),
        "starting_balance": starting_balance,
        "ending_balance":   round(balance, 4),
        "profit_factor":    round(gross_p / gross_l, 4) if gross_l > 0 else float("inf"),
        "avg_win_pct":      round(sum(t["pnl_pct"] for t in wins) / len(wins), 4) if wins else 0.0,
        "avg_loss_pct":     round(sum(t["pnl_pct"] for t in losses) / len(losses), 4) if losses else 0.0,
        "trade_log":        trades,
    }


# ============================================================================
# SINGLE COMBO EVALUATOR (runs in subprocess)
# ============================================================================

def _eval_combo(args: Tuple[Dict[str, Any], Dict[str, np.ndarray], str]) -> Dict[str, Any]:
    """
    Evaluate one parameter combination using pre-computed features.

    Designed to run inside ProcessPoolExecutor workers.
    Uses _fast_backtest (vectorised numpy) instead of VMRStrategy.run_backtest().

    Args:
        args: (params_dict, features_dict, symbol)

    Returns:
        Row dict: params + metrics (sharpe, return_pct, max_dd_pct, win_rate,
                  num_trades, profit_factor).
    """
    params, feats, symbol = args
    try:
        result = _fast_backtest(feats, params)
        sharpe = compute_sharpe(result, CANDLE_DAYS)

        row = {
            # params
            "spike_threshold_pct": params["spike_threshold_pct"],
            "bb_std_multiplier":   params["bb_std_multiplier"],
            "sl_pct":              params["sl_pct"],
            "tp_pct":              params["tp_pct"],
            "position_size_pct":   params["position_size_pct"],
            "max_hold_hours":      int(params["max_hold_hours"]),
            # metrics
            "sharpe":              sharpe,
            "return_pct":          result["return_pct"],
            "max_dd_pct":          result["max_dd_pct"],
            "win_rate":            result["win_rate"],
            "num_trades":          result["trades"],
            "profit_factor":       result["profit_factor"],
            "avg_win_pct":         result["avg_win_pct"],
            "avg_loss_pct":        result["avg_loss_pct"],
        }
        return row

    except Exception as exc:
        # Return a sentinel row on failure so we don't lose progress
        return {
            "spike_threshold_pct": params.get("spike_threshold_pct"),
            "bb_std_multiplier":   params.get("bb_std_multiplier"),
            "sl_pct":              params.get("sl_pct"),
            "tp_pct":              params.get("tp_pct"),
            "position_size_pct":   params.get("position_size_pct"),
            "max_hold_hours":      params.get("max_hold_hours"),
            "sharpe":              -999.0,
            "return_pct":          0.0,
            "max_dd_pct":          100.0,
            "win_rate":            0.0,
            "num_trades":          0,
            "profit_factor":       0.0,
            "avg_win_pct":         0.0,
            "avg_loss_pct":        0.0,
            "_error":              str(exc),
        }


# ============================================================================
# GRID SEARCH
# ============================================================================

def run_grid_search(
    symbol: str,
    df: pd.DataFrame,
    param_grid: Dict[str, List[Any]] = PARAM_GRID,
    workers: int = 4,
    dry_run: bool = False,
    progress_cb=None,
) -> pd.DataFrame:
    """
    Run exhaustive grid search over all parameter combinations.

    Uses multiprocessing (ProcessPoolExecutor) for speed.

    Args:
        symbol:      Instrument name (for logging / output filenames).
        df:          180d OHLCV DataFrame (already validated).
        param_grid:  Dict of {param_name: [values]}.
        workers:     Number of parallel worker processes.
        dry_run:     If True, only test 50 random combinations (smoke-test).
        progress_cb: Optional callable(done, total) called after each batch.

    Returns:
        DataFrame with one row per combination, sorted by Sharpe descending.
        Also saved to optimization_results_<SYMBOL>_<DATE>.csv.
    """
    keys  = list(param_grid.keys())
    combos = list(itertools.product(*[param_grid[k] for k in keys]))

    if dry_run:
        import random
        random.seed(42)
        combos = random.sample(combos, min(50, len(combos)))
        logger.info(f"[{symbol}] DRY RUN: testing {len(combos)} combinations")
    else:
        logger.info(f"[{symbol}] Grid search: {len(combos)} combinations, {workers} workers")

    # Pre-compute features ONCE — passed to all workers (numpy arrays, not DataFrame)
    logger.info(f"[{symbol}] Pre-computing candle features ...")
    feats = _precompute_features(df)
    logger.info(f"[{symbol}] Features ready ({feats['n']} bars)")

    tasks: List[Tuple[Dict[str, Any], Dict[str, np.ndarray], str]] = []
    for combo in combos:
        params = dict(zip(keys, combo))
        tasks.append((params, feats, symbol))

    results: List[Dict[str, Any]] = []
    done = 0
    start_t = time.time()

    # Chunk size for batching (reduces overhead)
    chunk = max(1, min(50, len(tasks) // workers))

    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_eval_combo, t): t for t in tasks}
        for fut in as_completed(futures):
            row = fut.result()
            results.append(row)
            done += 1

            if done % 100 == 0 or done == len(tasks):
                elapsed = time.time() - start_t
                rate    = done / elapsed if elapsed > 0 else 1
                eta_s   = (len(tasks) - done) / rate
                pct     = done / len(tasks) * 100
                logger.info(
                    f"[{symbol}] Progress: {done}/{len(tasks)} "
                    f"({pct:.1f}%) — ETA {eta_s/60:.1f} min"
                )
                if progress_cb:
                    progress_cb(done, len(tasks))

    results_df = pd.DataFrame(results)
    results_df = results_df.sort_values("sharpe", ascending=False).reset_index(drop=True)

    # Remove error sentinel column if present (all-NaN after successful runs)
    if "_error" in results_df.columns:
        error_rows = results_df["_error"].notna().sum()
        if error_rows > 0:
            logger.warning(f"[{symbol}] {error_rows} combinations had errors")
        results_df = results_df.drop(columns=["_error"])

    # Save CSV
    out_path = RESULTS_DIR / f"optimization_results_{symbol}_{TODAY_STR}.csv"
    results_df.to_csv(out_path, index=False)
    elapsed_total = time.time() - start_t
    logger.info(
        f"[{symbol}] Grid search complete in {elapsed_total/60:.1f} min — "
        f"results → {out_path}"
    )

    return results_df


# ============================================================================
# SUMMARY GENERATION
# ============================================================================

def _df_to_md_table(df: pd.DataFrame, max_rows: int = 20) -> str:
    """Format a DataFrame as a Markdown table (top N rows)."""
    top = df.head(max_rows).copy()

    # Round for readability
    float_cols = top.select_dtypes(include="float").columns
    top[float_cols] = top[float_cols].round(4)

    col_widths = {col: max(len(col), top[col].astype(str).str.len().max())
                  for col in top.columns}

    header = " | ".join(col.ljust(col_widths[col]) for col in top.columns)
    sep    = "-|-".join("-" * col_widths[col] for col in top.columns)
    rows   = [
        " | ".join(str(row[col]).ljust(col_widths[col]) for col in top.columns)
        for _, row in top.iterrows()
    ]
    return "\n".join(["| " + header + " |", "|-" + sep + "-|"] + ["| " + r + " |" for r in rows])


def generate_summary(
    per_symbol_results: Dict[str, pd.DataFrame],
    data_quality: Dict[str, Dict[str, Any]],
) -> str:
    """
    Build optimization_summary.md content.

    Shows:
    • Data quality report per symbol
    • Top 20 combos per symbol (ranked by Sharpe)
    • Overall top 10 (equal-weighted average Sharpe across all symbols)

    Args:
        per_symbol_results: {symbol: results_df}
        data_quality:       {symbol: quality_stats_dict}

    Returns:
        Full Markdown string.
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    md  = [
        f"# VMR Strategy Optimization Summary",
        f"",
        f"Generated: {now}  ",
        f"Window: {CANDLE_DAYS}d of 1h candles  ",
        f"Total parameter combinations: {TOTAL_COMBOS:,}  ",
        f"",
        f"---",
        f"",
    ]

    # ── Data quality ─────────────────────────────────────────────────────────
    md.append("## Data Quality")
    md.append("")
    for symbol, q in data_quality.items():
        status = "✅" if q.get("quality_ok") else "⚠️"
        md.append(f"### {status} {symbol}")
        md.append(f"- Bars fetched: {q.get('total_bars', '?')} "
                  f"(expected {q.get('expected_bars', CANDLE_HOURS)})")
        md.append(f"- Coverage: {q.get('coverage_pct', 0):.1f}%")
        md.append(f"- From: {q.get('date_from','?')} → {q.get('date_to','?')}")
        md.append(f"- Gaps detected: {q.get('gap_count', 0)}")
        md.append(f"- Mean hourly return: {q.get('mean_return_pct',0):.4f}%  "
                  f"std: {q.get('std_return_pct',0):.4f}%")
        if q.get("warnings"):
            for w in q["warnings"]:
                md.append(f"  - ⚠️ {w}")
        md.append("")

    md.append("---")
    md.append("")

    # ── Per-symbol top 20 ────────────────────────────────────────────────────
    md.append("## Top Results per Symbol")
    md.append("")

    display_cols = [
        "spike_threshold_pct", "bb_std_multiplier", "sl_pct", "tp_pct",
        "position_size_pct", "max_hold_hours",
        "sharpe", "return_pct", "max_dd_pct", "win_rate", "num_trades",
    ]

    for symbol, df in per_symbol_results.items():
        if df.empty:
            md.append(f"### {symbol} — no results")
            continue

        top20 = df.head(20).copy()
        md.append(f"### {symbol} — Top 20 by Sharpe")
        md.append("")

        # Build table manually for clean formatting
        cols = [c for c in display_cols if c in top20.columns]
        top20_display = top20[cols].reset_index(drop=True)
        top20_display.insert(0, "rank", range(1, len(top20_display) + 1))

        md.append(_df_to_md_table(top20_display, max_rows=20))
        md.append("")

        # Winner summary
        best = df.iloc[0]
        md.append(f"**Best combo ({symbol}):**")
        md.append(f"- Sharpe: `{best['sharpe']:.4f}`")
        md.append(f"- Return: `{best['return_pct']:+.2f}%`")
        md.append(f"- Max DD: `{best['max_dd_pct']:.2f}%`")
        md.append(f"- Win rate: `{best['win_rate']:.1f}%`")
        md.append(f"- Trades: `{int(best['num_trades'])}`")
        md.append(f"- Params: `spike={best['spike_threshold_pct']}`, "
                  f"`bb_mult={best['bb_std_multiplier']}`, "
                  f"`sl={best['sl_pct']}`, "
                  f"`tp={best['tp_pct']}`, "
                  f"`size={best['position_size_pct']}`, "
                  f"`hold={int(best['max_hold_hours'])}h`")
        md.append("")

    md.append("---")
    md.append("")

    # ── Overall top 10 (equal-weight average Sharpe) ─────────────────────────
    md.append("## Overall Top 10 (Average Sharpe — All Symbols)")
    md.append("")

    if len(per_symbol_results) > 1:
        # Merge on param columns, compute mean Sharpe across symbols
        param_cols = [
            "spike_threshold_pct", "bb_std_multiplier", "sl_pct",
            "tp_pct", "position_size_pct", "max_hold_hours",
        ]
        combined: Optional[pd.DataFrame] = None
        for symbol, df in per_symbol_results.items():
            if df.empty:
                continue
            sub = df[param_cols + ["sharpe", "return_pct", "max_dd_pct",
                                   "win_rate", "num_trades"]].copy()
            sub = sub.rename(columns={
                "sharpe":      f"sharpe_{symbol}",
                "return_pct":  f"return_{symbol}",
                "max_dd_pct":  f"dd_{symbol}",
                "win_rate":    f"wr_{symbol}",
                "num_trades":  f"trades_{symbol}",
            })
            if combined is None:
                combined = sub
            else:
                combined = pd.merge(combined, sub, on=param_cols, how="outer")

        if combined is not None and not combined.empty:
            sharpe_cols = [c for c in combined.columns if c.startswith("sharpe_")]
            combined["avg_sharpe"] = combined[sharpe_cols].mean(axis=1)
            combined = combined.sort_values("avg_sharpe", ascending=False).reset_index(drop=True)

            top10 = combined.head(10)[param_cols + ["avg_sharpe"] + sharpe_cols].copy()
            top10.insert(0, "rank", range(1, len(top10) + 1))
            md.append(_df_to_md_table(top10, max_rows=10))
            md.append("")

            # Save best-params file (top-3 overall combos)
            best_params_list = []
            for i in range(min(3, len(combined))):
                row = combined.iloc[i]
                bp = {
                    "rank":   i + 1,
                    "params": {pc: float(row[pc]) for pc in param_cols},
                    "avg_sharpe": float(row["avg_sharpe"]),
                }
                for sc in sharpe_cols:
                    sym = sc.replace("sharpe_", "")
                    bp[f"sharpe_{sym}"] = float(row[sc]) if not pd.isna(row[sc]) else None
                best_params_list.append(bp)

            with open(BEST_PARAMS_FILE, "w") as f:
                json.dump({
                    "generated": now,
                    "top_combos": best_params_list,
                }, f, indent=2)
            logger.info(f"Best params saved → {BEST_PARAMS_FILE}")

    elif len(per_symbol_results) == 1:
        symbol = list(per_symbol_results.keys())[0]
        df = per_symbol_results[symbol]
        if not df.empty:
            top10 = df.head(10)[display_cols].copy()
            top10.insert(0, "rank", range(1, len(top10) + 1))
            md.append(_df_to_md_table(top10, max_rows=10))
            md.append("")

            # Save best params for single-symbol run
            best_params_list = []
            for i in range(min(3, len(df))):
                row = df.iloc[i]
                param_cols = [
                    "spike_threshold_pct", "bb_std_multiplier", "sl_pct",
                    "tp_pct", "position_size_pct", "max_hold_hours",
                ]
                bp = {
                    "rank":   i + 1,
                    "params": {pc: float(row[pc]) for pc in param_cols},
                    "avg_sharpe": float(row["sharpe"]),
                    f"sharpe_{symbol}": float(row["sharpe"]),
                }
                best_params_list.append(bp)

            with open(BEST_PARAMS_FILE, "w") as f:
                json.dump({
                    "generated": now,
                    "top_combos": best_params_list,
                }, f, indent=2)

    md.append("---")
    md.append("")
    md.append("## How to Apply Best Params")
    md.append("")
    md.append("Via Telegram bot commands:")
    md.append("```")
    md.append("/show_best_params          — display top 3 combos")
    md.append("/set_params spike=1.0 bb_mult=2.0 sl=0.005 tp=0.015 size=0.01 hold=24")
    md.append("/backtest BTC 30 --use-optimized-params")
    md.append("```")
    md.append("")

    return "\n".join(md)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="VMR parameter grid-search optimizer"
    )
    parser.add_argument(
        "--symbol", nargs="+", default=SYMBOLS,
        help=f"Symbol(s) to optimize (default: {' '.join(SYMBOLS)})"
    )
    parser.add_argument(
        "--workers", type=int,
        default=max(1, multiprocessing.cpu_count() - 1),
        help="Parallel worker processes (default: cpu_count-1)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Quick test with 50 random combinations per symbol"
    )
    parser.add_argument(
        "--no-cache", action="store_true",
        help="Force re-fetch candles even if cache exists"
    )
    args = parser.parse_args()

    logger.info("=" * 65)
    logger.info("VMR Parameter Optimizer")
    logger.info(f"Symbols:    {', '.join(args.symbol)}")
    logger.info(f"Workers:    {args.workers}")
    logger.info(f"Dry run:    {args.dry_run}")
    logger.info(f"Total grid: {TOTAL_COMBOS:,} combinations per symbol")
    logger.info("=" * 65)

    per_symbol_results: Dict[str, pd.DataFrame] = {}
    data_quality:       Dict[str, Dict[str, Any]] = {}

    total_start = time.time()

    for symbol in args.symbol:
        logger.info(f"\n{'='*65}")
        logger.info(f"[{symbol}] Starting optimization")
        logger.info(f"{'='*65}")

        # ── 1. Fetch data ─────────────────────────────────────────────────
        df = fetch_180d_candles(symbol, use_cache=not args.no_cache)
        if df is None or df.empty:
            logger.error(f"[{symbol}] No data available — skipping")
            per_symbol_results[symbol] = pd.DataFrame()
            data_quality[symbol] = {"quality_ok": False, "warnings": ["No data"]}
            continue

        # ── 2. Validate ───────────────────────────────────────────────────
        qstats = validate_data(df, symbol)
        data_quality[symbol] = qstats

        if not qstats["quality_ok"]:
            logger.warning(f"[{symbol}] Data quality issues — proceeding anyway")

        # ── 3. Grid search ────────────────────────────────────────────────
        results_df = run_grid_search(
            symbol    = symbol,
            df        = df,
            param_grid= PARAM_GRID,
            workers   = args.workers,
            dry_run   = args.dry_run,
        )
        per_symbol_results[symbol] = results_df

        # Log top 5
        logger.info(f"\n[{symbol}] TOP 5 COMBINATIONS:")
        logger.info(f"{'Sharpe':>8}  {'Return%':>8}  {'MaxDD%':>7}  {'WinRate%':>9}  {'Trades':>6}  Params")
        for i, row in results_df.head(5).iterrows():
            logger.info(
                f"{row['sharpe']:8.4f}  "
                f"{row['return_pct']:8.2f}  "
                f"{row['max_dd_pct']:7.2f}  "
                f"{row['win_rate']:9.1f}  "
                f"{int(row['num_trades']):6d}  "
                f"spike={row['spike_threshold_pct']} "
                f"bb={row['bb_std_multiplier']} "
                f"sl={row['sl_pct']} "
                f"tp={row['tp_pct']} "
                f"size={row['position_size_pct']} "
                f"hold={int(row['max_hold_hours'])}h"
            )

    # ── 4. Generate summary ───────────────────────────────────────────────────
    logger.info("\nGenerating optimization_summary.md ...")
    summary_md = generate_summary(per_symbol_results, data_quality)
    summary_path = REPO_ROOT / "optimization_summary.md"
    with open(summary_path, "w") as f:
        f.write(summary_md)
    logger.info(f"Summary → {summary_path}")

    total_elapsed = time.time() - total_start
    logger.info(f"\n{'='*65}")
    logger.info(f"Optimization complete in {total_elapsed/60:.1f} min")
    logger.info(f"Results: {RESULTS_DIR}/")
    logger.info(f"Summary: {summary_path}")
    logger.info(f"Best params: {BEST_PARAMS_FILE}")
    logger.info(f"{'='*65}")


if __name__ == "__main__":
    main()
