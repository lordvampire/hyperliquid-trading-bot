"""
WalkForwardValidator — Rolling-window out-of-sample validation.

Split cadence (default):
    window_size = 180 days training
    test_size   =  60 days testing
    stride      =  60 days (non-overlapping test windows)

Usage:
    from config.manager import ConfigManager
    from strategies.strategy_b import StrategyB
    from backtest_validator import WalkForwardValidator

    config   = ConfigManager("config/base.yaml", "backtest")
    strategy = StrategyB(config.strategy("strategy_b"), "backtest")
    validator = WalkForwardValidator(strategy, config)
    results  = validator.run_walk_forward("BTC", days=360)
    print(f"Avg Sharpe: {results['avg_sharpe']:.2f}")
    print(f"Consistency: {results['consistency']:.2%}")
"""

from __future__ import annotations
import logging
import math
import random
from typing import Any, Dict, List, Optional

import pandas as pd

from strategies.base import StrategyBase
from config.manager import ConfigManager
from backtest_engine_v2 import BacktestEngineV2

logger = logging.getLogger(__name__)


class WalkForwardValidator:
    """
    Walk-forward validation using rolling train/test windows.

    Args:
        strategy:    Any StrategyBase implementation.
        config:      ConfigManager instance.
        split_ratio: Kept for API compatibility (not used — window_size / test_size are explicit).
    """

    def __init__(
        self,
        strategy: StrategyBase,
        config: ConfigManager,
        split_ratio: float = 0.8,
    ):
        self.strategy    = strategy
        self.config      = config
        self.split_ratio = split_ratio
        self.engine      = BacktestEngineV2(strategy, config)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_walk_forward(
        self,
        symbol: str,
        days: int,
        window_size: int = 180,
        test_size: int = 60,
    ) -> Dict[str, Any]:
        """
        Run rolling-window walk-forward validation.

        Args:
            symbol:      Instrument ticker (e.g. "BTC").
            days:        Total history in days (train + test combined).
            window_size: Training window length in days.
            test_size:   Test window length in days.

        Returns:
            Aggregated metrics dict (avg_sharpe, avg_win_rate, avg_max_dd,
            consistency, windows, overfitting_detected, window_results).
        """
        total_candles = days * 24

        # Load (or synthesise) price data for the full period
        data = self._load_or_synthesise(symbol, total_candles)
        if data is None or data.empty:
            logger.error(f"[WalkForward] No data for {symbol}")
            return {"error": f"No data available for {symbol}"}

        train_bars = window_size * 24
        test_bars  = test_size  * 24
        stride     = test_bars           # slide by one test window

        window_results: List[Dict] = []
        start = 0

        while start + train_bars + test_bars <= len(data):
            train_end  = start + train_bars
            test_end   = train_end + test_bars

            train_df = data.iloc[start:train_end].reset_index(drop=True)
            test_df  = data.iloc[train_end:test_end].reset_index(drop=True)

            # Train metrics (in-sample)
            train_result = self._run_window(symbol, train_df, window_size)
            # Test metrics (out-of-sample)
            test_result  = self._run_window(symbol, test_df, test_size)

            is_overfit = self.detect_overfitting(
                train_result.get("sharpe", 0.0),
                test_result.get("sharpe", 0.0),
            )

            window_results.append({
                "window_start_bar": start,
                "train_days":  window_size,
                "test_days":   test_size,
                "train":       train_result,
                "test":        test_result,
                "overfit":     is_overfit,
            })

            logger.info(
                f"[WalkForward] Window {len(window_results)}: "
                f"train_sharpe={train_result.get('sharpe', 0):.2f} "
                f"test_sharpe={test_result.get('sharpe', 0):.2f} "
                f"overfit={is_overfit}"
            )

            start += stride

        if not window_results:
            return {
                "error": (
                    f"Insufficient data: {days} days < "
                    f"{window_size + test_size} days required for one window"
                )
            }

        aggregated = self.aggregate_results(window_results)
        aggregated["symbol"]       = symbol
        aggregated["days"]         = days
        aggregated["windows"]      = len(window_results)
        aggregated["window_results"] = window_results
        return aggregated

    def aggregate_results(self, results: List[Dict]) -> Dict[str, Any]:
        """
        Aggregate per-window test results into summary stats.

        Args:
            results: List of window dicts from run_walk_forward.

        Returns:
            dict with avg_sharpe, avg_max_dd, avg_win_rate, consistency,
            overfitting_detected.
        """
        test_sharpes  = [r["test"].get("sharpe",   0.0) for r in results]
        test_dds      = [r["test"].get("max_dd",   0.0) for r in results]
        test_wrs      = [r["test"].get("win_rate", 0.0) for r in results]

        n = len(results)
        avg_sharpe   = sum(test_sharpes) / n
        avg_max_dd   = sum(test_dds)     / n
        avg_win_rate = sum(test_wrs)     / n

        # Consistency = 1 - coefficient of variation of Sharpe (lower std → higher consistency)
        if avg_sharpe != 0 and n > 1:
            variance    = sum((s - avg_sharpe) ** 2 for s in test_sharpes) / n
            std_sharpe  = math.sqrt(variance)
            cv          = abs(std_sharpe / avg_sharpe) if avg_sharpe != 0 else 1.0
            consistency = max(0.0, 1.0 - cv)
        else:
            std_sharpe  = 0.0
            consistency = 1.0 if n == 1 else 0.0

        overfitting_detected = any(r["overfit"] for r in results)

        return {
            "avg_sharpe":          round(avg_sharpe,   4),
            "avg_max_dd":          round(avg_max_dd,   4),
            "avg_win_rate":        round(avg_win_rate / 100, 4),  # as fraction
            "std_sharpe":          round(std_sharpe,   4),
            "consistency":         round(consistency,  4),
            "overfitting_detected": overfitting_detected,
        }

    def detect_overfitting(self, train_sharpe: float, test_sharpe: float) -> bool:
        """
        Flag overfitting if test Sharpe degrades significantly vs train.

        Rule: test_sharpe < 0.5 * train_sharpe  (and train_sharpe > 0)
        """
        if train_sharpe <= 0:
            return False
        return test_sharpe < 0.5 * train_sharpe

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _run_window(self, symbol: str, data: pd.DataFrame, days: int) -> Dict[str, Any]:
        """Run backtest on a data slice and return metrics + Sharpe estimate."""
        signals  = self.strategy.generate_signals(data)
        raw_stats = self.engine._simulate(data, signals, symbol)

        # Derive Sharpe from return and max_dd as a proxy
        ret = raw_stats.get("return_pct", 0.0)
        dd  = raw_stats.get("max_dd", 1.0) or 1.0
        sharpe = ret / dd if dd else 0.0

        return {
            **raw_stats,
            "sharpe": round(sharpe, 4),
            "days":   days,
        }

    def _load_or_synthesise(self, symbol: str, num_candles: int) -> Optional[pd.DataFrame]:
        """
        Try to fetch live OHLCV data; fall back to a random-walk simulation.

        The synthetic data produces realistic-ish crypto price series for
        scaffold testing — NOT for production signal evaluation.
        """
        try:
            from exchange import fetch_candles  # type: ignore
            raw = fetch_candles(symbol, "1h", num_candles)
            candles = raw if isinstance(raw, list) else raw.get("candles", [])
            rows = []
            for c in candles:
                if isinstance(c, dict):
                    rows.append({
                        "open":   float(c.get("o", c.get("open", 0))),
                        "high":   float(c.get("h", c.get("high", 0))),
                        "low":    float(c.get("l", c.get("low", 0))),
                        "close":  float(c.get("c", c.get("close", 0))),
                        "volume": float(c.get("v", c.get("volume", 1.0))),
                    })
            if len(rows) >= 50:
                logger.info(f"[WalkForward] Loaded {len(rows)} live candles for {symbol}")
                return pd.DataFrame(rows)
        except Exception as exc:
            logger.debug(f"[WalkForward] Live data unavailable ({exc}); using synthetic data")

        # Synthetic random-walk fallback
        logger.info(f"[WalkForward] Generating {num_candles} synthetic candles for {symbol}")
        return self._synthesise_ohlcv(num_candles, seed=hash(symbol) % 2**32)

    @staticmethod
    def _synthesise_ohlcv(n: int, seed: int = 42) -> pd.DataFrame:
        """Generate a random-walk OHLCV DataFrame for testing purposes."""
        rng   = random.Random(seed)
        price = 45_000.0
        rows  = []
        for _ in range(n):
            change  = rng.gauss(0.0002, 0.015)  # slight upward drift
            close   = price * (1 + change)
            high    = max(price, close) * (1 + abs(rng.gauss(0, 0.005)))
            low     = min(price, close) * (1 - abs(rng.gauss(0, 0.005)))
            volume  = rng.uniform(50, 500)
            rows.append({
                "open":   round(price, 2),
                "high":   round(high,  2),
                "low":    round(low,   2),
                "close":  round(close, 2),
                "volume": round(volume, 2),
            })
            price = close
        return pd.DataFrame(rows)
