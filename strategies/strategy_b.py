"""
Strategy B — Multi-factor momentum strategy (OHLCV-based).

Signals are built from three normalised sub-scores:
  • Momentum  (fast vs slow MA cross + 5-bar price change)
  • RSI       (distance from midpoint 50)
  • Volume    (current bar vs rolling average)

All parameters come from self.config — zero hardcoding.
"""

from __future__ import annotations
from typing import Any, Dict, List

import pandas as pd

from strategies.base import Signal, StrategyBase


class StrategyB(StrategyBase):
    """
    Composite momentum strategy for backtesting and live execution.

    Config keys required (see config/base.yaml → strategies.strategy_b):
        fast_period, slow_period, rsi_period,
        momentum_weight, rsi_weight, volume_weight,
        entry_threshold, exit_threshold,
        stop_pct, tp_pct
    """

    REQUIRED = [
        "fast_period", "slow_period", "rsi_period",
        "momentum_weight", "rsi_weight", "volume_weight",
        "entry_threshold", "exit_threshold",
        "stop_pct", "tp_pct",
    ]

    def required_params(self) -> List[str]:
        return list(self.REQUIRED)

    def get_params(self) -> Dict[str, Any]:
        return dict(self.config)

    # ------------------------------------------------------------------
    # Core signal generation
    # ------------------------------------------------------------------

    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """
        Generate signals for every bar where enough history exists.

        Args:
            data: DataFrame with columns [open, high, low, close, volume].
                  Index is arbitrary (int or DatetimeIndex).

        Returns:
            List of Signal objects.  Non-HOLD signals have stop_loss /
            take_profit set relative to the bar's close price.
        """
        if data.empty or len(data) < self.config["slow_period"]:
            return []

        closes = data["close"].tolist()
        volumes = data["volume"].tolist() if "volume" in data.columns else [1.0] * len(data)

        signals: List[Signal] = []
        min_idx = max(self.config["slow_period"], self.config["rsi_period"]) + 1

        for i in range(min_idx, len(closes)):
            score, subscores = self._composite_score(closes, volumes, i)
            direction, strength = self._classify(score)

            close = closes[i]
            stop_loss = 0.0
            take_profit = 0.0
            if direction == "LONG":
                stop_loss = close * (1 - self.config["stop_pct"])
                take_profit = close * (1 + self.config["tp_pct"])
            elif direction == "SHORT":
                stop_loss = close * (1 + self.config["stop_pct"])
                take_profit = close * (1 - self.config["tp_pct"])

            signals.append(Signal(
                symbol=data.get("symbol", [None] * len(closes))[i] if "symbol" in data.columns else "",
                direction=direction,
                strength=round(abs(strength), 4),
                stop_loss=round(stop_loss, 6),
                take_profit=round(take_profit, 6),
                metadata={
                    "bar_index": i,
                    "composite_score": round(score, 4),
                    **{f"score_{k}": round(v, 4) for k, v in subscores.items()},
                    "close": close,
                },
            ))

        return signals

    # ------------------------------------------------------------------
    # Sub-indicators (all accept full lists + current index)
    # ------------------------------------------------------------------

    def _composite_score(self, closes: list, volumes: list, i: int):
        """Return (composite_score ∈ [-1, 1], subscores dict)."""
        mom = self._momentum_score(closes, i)
        rsi_s = self._rsi_score(closes, i)
        vol_s = self._volume_score(volumes, i)

        w_mom = self.config["momentum_weight"]
        w_rsi = self.config["rsi_weight"]
        w_vol = self.config["volume_weight"]

        composite = (mom * w_mom + rsi_s * w_rsi + vol_s * w_vol) / (w_mom + w_rsi + w_vol)
        return composite, {"momentum": mom, "rsi": rsi_s, "volume": vol_s}

    def _momentum_score(self, closes: list, i: int) -> float:
        """Score in [-1, 1]: fast MA vs slow MA cross + short-term change."""
        fp = self.config["fast_period"]
        sp = self.config["slow_period"]
        fast_ma = sum(closes[i - fp + 1: i + 1]) / fp
        slow_ma = sum(closes[i - sp + 1: i + 1]) / sp
        cross = (fast_ma - slow_ma) / slow_ma if slow_ma else 0.0

        # 5-bar change normalised
        lookback = min(fp, i)
        change = (closes[i] - closes[i - lookback]) / closes[i - lookback] if closes[i - lookback] else 0.0

        raw = (cross + change) / 2
        return max(-1.0, min(1.0, raw * 20))  # scale: 5% move → ±1

    def _rsi_score(self, closes: list, i: int) -> float:
        """Score in [-1, 1]: RSI above 50 → positive, below → negative."""
        period = self.config["rsi_period"]
        rsi = self._rsi(closes[max(0, i - period * 2): i + 1], period)
        return (rsi - 50) / 50  # maps [0,100] → [-1, 1]

    def _volume_score(self, volumes: list, i: int) -> float:
        """Score in [-1, 1]: current volume vs rolling average (capped at ±1)."""
        sp = self.config["slow_period"]
        window = volumes[max(0, i - sp): i]
        if not window:
            return 0.0
        avg = sum(window) / len(window)
        if avg == 0:
            return 0.0
        ratio = volumes[i] / avg - 1.0  # 0 = average
        return max(-1.0, min(1.0, ratio))

    @staticmethod
    def _rsi(closes: list, period: int) -> float:
        if len(closes) < period + 1:
            return 50.0
        deltas = [closes[j] - closes[j - 1] for j in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas[-period:]]
        losses = [-d if d < 0 else 0 for d in deltas[-period:]]
        avg_gain = sum(gains) / period
        avg_loss = sum(losses) / period
        if avg_loss == 0:
            return 100.0 if avg_gain > 0 else 50.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    # ------------------------------------------------------------------
    # Signal classification
    # ------------------------------------------------------------------

    def _classify(self, score: float):
        """Map composite score → (direction, strength)."""
        if score > self.config["entry_threshold"]:
            return "LONG", score
        if score < -self.config["entry_threshold"]:
            return "SHORT", score
        return "HOLD", score
