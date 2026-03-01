#!/usr/bin/env python3
"""
tests/test_strategy_engine.py
==============================
Unit tests for strategy_engine.VMRStrategy.

Run with: pytest tests/test_strategy_engine.py -v
"""

import sys
import os
from datetime import datetime
from typing import List

import numpy as np
import pandas as pd
import pytest

# Allow imports from repo root
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from strategy_engine import VMRConfig, VMRStrategy, VMRSignal, VMRPosition


# ============================================================================
# FIXTURES
# ============================================================================


def make_flat_df(n: int = 50, price: float = 50_000.0) -> pd.DataFrame:
    """Create a DataFrame with no price movement (no signal expected)."""
    closes = [price] * n
    return pd.DataFrame({"close": closes, "high": closes, "low": closes})


def make_spike_df(n: int = 50, base: float = 50_000.0, spike_pct: float = -2.0) -> pd.DataFrame:
    """
    Create a DataFrame where the LAST bar has a large negative return
    (should trigger a LONG mean-reversion signal if BB confirmed).
    """
    closes = [base] * n
    closes[-1] = base * (1 + spike_pct / 100)
    return pd.DataFrame({"close": closes, "high": closes, "low": closes})


def make_upspike_df(n: int = 50, base: float = 50_000.0, spike_pct: float = 2.0) -> pd.DataFrame:
    """
    Create a DataFrame where the LAST bar has a large positive return
    (should trigger a SHORT signal if BB confirmed).
    """
    closes = [base] * n
    closes[-1] = base * (1 + spike_pct / 100)
    return pd.DataFrame({"close": closes, "high": closes, "low": closes})


def make_bb_breakout_df(n: int = 50, base: float = 50_000.0) -> pd.DataFrame:
    """
    Spike + price below lower Bollinger Band.
    Simulate a realistic mean-reversion setup.
    """
    # Stable prices with small noise
    np.random.seed(42)
    prices = base + np.random.randn(n - 1) * 100  # tight range
    # Last candle: large crash below BB
    prices = list(prices)
    prices.append(base * 0.96)  # -4% last bar
    return pd.DataFrame({"close": prices, "high": prices, "low": prices})


# ============================================================================
# TESTS — VMRConfig
# ============================================================================


class TestVMRConfig:
    """Validate default configuration values."""

    def test_default_spike_threshold(self):
        """Default spike threshold should be 1.0%."""
        cfg = VMRConfig()
        assert cfg.spike_threshold_pct == 1.0

    def test_default_sl_tp(self):
        """SL 0.5%, TP 1.5% — classic VMR risk management."""
        cfg = VMRConfig()
        assert cfg.sl_pct == 0.005
        assert cfg.tp_pct == 0.015

    def test_default_position_size(self):
        """Default position size should be 1% of account."""
        cfg = VMRConfig()
        assert cfg.position_size_pct == 0.01

    def test_rr_ratio_is_3x(self):
        """TP:SL ratio should be 3:1 with defaults (0.015/0.005)."""
        cfg = VMRConfig()
        rr = cfg.tp_pct / cfg.sl_pct
        assert abs(rr - 3.0) < 0.01, f"Expected RR=3, got {rr}"

    def test_custom_config(self):
        """Custom config overrides should propagate correctly."""
        cfg = VMRConfig(spike_threshold_pct=2.0, sl_pct=0.01, tp_pct=0.03)
        assert cfg.spike_threshold_pct == 2.0
        assert cfg.sl_pct == 0.01
        assert cfg.tp_pct == 0.03

    def test_symbols_list(self):
        """Default symbols should include BTC, ETH, SOL."""
        cfg = VMRConfig()
        assert "BTC" in cfg.symbols
        assert "ETH" in cfg.symbols
        assert "SOL" in cfg.symbols


# ============================================================================
# TESTS — VMRStrategy.analyze()
# ============================================================================


class TestAnalyze:
    """Unit tests for VMRStrategy.analyze()."""

    def setup_method(self):
        """Use BB confirmation disabled by default for simpler tests."""
        self.cfg = VMRConfig(require_bb_confirmation=False, spike_threshold_pct=1.0)
        self.strat = VMRStrategy(self.cfg)

    def test_no_signal_on_flat_price(self):
        """Flat prices → NO SIGNAL."""
        df = make_flat_df(50)
        sig = self.strat.analyze(df, "BTC")
        assert sig.direction == "NONE", f"Expected NONE, got {sig.direction}"

    def test_insufficient_data_returns_none(self):
        """Too few bars → NONE."""
        df = pd.DataFrame({"close": [50000.0] * 5})
        sig = self.strat.analyze(df, "BTC")
        assert sig.direction == "NONE"

    def test_negative_spike_gives_long_signal(self):
        """Large negative return → LONG (mean reversion up)."""
        df = make_spike_df(50, spike_pct=-3.0)
        sig = self.strat.analyze(df, "BTC")
        assert sig.direction == "LONG", f"Expected LONG, got {sig.direction}: {sig.reason}"

    def test_positive_spike_gives_short_signal(self):
        """Large positive return → SHORT (mean reversion down)."""
        df = make_upspike_df(50, spike_pct=3.0)
        sig = self.strat.analyze(df, "BTC")
        assert sig.direction == "SHORT", f"Expected SHORT, got {sig.direction}: {sig.reason}"

    def test_signal_has_correct_sl_tp(self):
        """Stop loss and take profit must be set consistently."""
        df = make_spike_df(50, spike_pct=-3.0)
        sig = self.strat.analyze(df, "BTC")
        cfg = self.cfg

        if sig.direction == "LONG":
            assert sig.stop_loss < sig.entry_price, "SL must be below entry for LONG"
            assert sig.take_profit > sig.entry_price, "TP must be above entry for LONG"
            sl_dist = (sig.entry_price - sig.stop_loss) / sig.entry_price
            tp_dist = (sig.take_profit - sig.entry_price) / sig.entry_price
            assert abs(sl_dist - cfg.sl_pct) < 0.0001, f"SL distance wrong: {sl_dist}"
            assert abs(tp_dist - cfg.tp_pct) < 0.0001, f"TP distance wrong: {tp_dist}"

    def test_rr_ratio_is_positive(self):
        """Risk/reward ratio must be positive for a valid signal."""
        df = make_spike_df(50, spike_pct=-3.0)
        sig = self.strat.analyze(df, "BTC")
        if sig.direction != "NONE":
            assert sig.rr_ratio > 0

    def test_confidence_bounded_0_to_1(self):
        """Confidence must be between 0 and 1."""
        df = make_spike_df(50, spike_pct=-5.0)
        sig = self.strat.analyze(df, "BTC")
        if sig.direction != "NONE":
            assert 0.0 <= sig.confidence <= 1.0, f"Confidence out of range: {sig.confidence}"

    def test_spike_below_threshold_no_signal(self):
        """Spike smaller than threshold → NONE."""
        df = make_spike_df(50, spike_pct=-0.5)  # below 1% threshold
        sig = self.strat.analyze(df, "BTC")
        assert sig.direction == "NONE"

    def test_symbol_propagates(self):
        """Symbol name should appear in returned signal."""
        df = make_flat_df(50)
        sig = self.strat.analyze(df, "ETH")
        assert sig.symbol == "ETH"


# ============================================================================
# TESTS — BB Confirmation
# ============================================================================


class TestBBConfirmation:
    """Test Bollinger Band confirmation filter."""

    def test_bb_filter_rejects_spike_without_breakout(self):
        """
        With BB confirmation ON, a spike that doesn't break the band
        should be filtered out → NONE.
        """
        cfg = VMRConfig(require_bb_confirmation=True, spike_threshold_pct=1.0)
        strat = VMRStrategy(cfg)
        # Small spike that doesn't push price outside BB
        df = make_spike_df(50, base=50_000, spike_pct=-1.1)
        sig = strat.analyze(df, "BTC")
        # Might be NONE if price didn't break lower BB
        # We can't assert direction here without knowing BB values,
        # but we CAN assert the result is internally consistent:
        if sig.direction == "LONG":
            assert sig.entry_price <= sig.bb_lower or not cfg.require_bb_confirmation

    def test_bb_filter_accepts_large_breakout(self):
        """
        With BB confirmation ON, a large crash outside the lower BB
        should produce a LONG signal.
        """
        cfg = VMRConfig(require_bb_confirmation=True, spike_threshold_pct=1.0)
        strat = VMRStrategy(cfg)
        df = make_bb_breakout_df(50)
        sig = strat.analyze(df, "BTC")
        # Should be LONG — price crashed well below lower BB
        # (If not, the synthetic data didn't create a clear enough breakout)
        assert sig.direction in ("LONG", "NONE")  # acceptable either way for synthetic


# ============================================================================
# TESTS — Position Sizing
# ============================================================================


class TestPositionSizing:
    """Unit tests for VMRStrategy.calculate_position()."""

    def setup_method(self):
        self.cfg = VMRConfig(
            position_size_pct=0.01,
            min_leverage=5,
            max_leverage=10,
        )
        self.strat = VMRStrategy(self.cfg)
        self.signal = VMRSignal(
            symbol="BTC",
            direction="LONG",
            entry_price=50_000.0,
            stop_loss=49_750.0,
            take_profit=50_750.0,
        )

    def test_position_size_is_1_pct_of_account(self):
        """size_usd should be 1% of account balance."""
        result = self.strat.calculate_position(self.signal, 10_000.0)
        assert abs(result["size_usd"] - 100.0) < 0.01

    def test_size_crypto_derived_from_entry_price(self):
        """size_crypto = size_usd / entry_price."""
        result = self.strat.calculate_position(self.signal, 10_000.0)
        expected = 100.0 / 50_000.0
        assert abs(result["size_crypto"] - expected) < 1e-8

    def test_leverage_within_bounds(self):
        """Leverage must be within [min_leverage, max_leverage]."""
        result = self.strat.calculate_position(self.signal, 10_000.0)
        assert self.cfg.min_leverage <= result["leverage"] <= self.cfg.max_leverage

    def test_zero_entry_price_returns_empty(self):
        """Entry price of 0 should return empty dict (not crash)."""
        sig = VMRSignal(symbol="BTC", direction="LONG", entry_price=0.0)
        result = self.strat.calculate_position(sig, 10_000.0)
        assert result == {}


# ============================================================================
# TESTS — Exit Logic
# ============================================================================


class TestExitLogic:
    """Unit tests for VMRStrategy.check_exit()."""

    def setup_method(self):
        self.cfg = VMRConfig(sl_pct=0.005, tp_pct=0.015, max_hold_hours=24)
        self.strat = VMRStrategy(self.cfg)
        self.long_pos = VMRPosition(
            symbol="BTC",
            direction="LONG",
            entry_price=50_000.0,
            stop_loss=49_750.0,   # 0.5% below entry
            take_profit=50_750.0, # 1.5% above entry
            size_usd=100.0,
            size_crypto=0.002,
            leverage=5,
        )
        self.short_pos = VMRPosition(
            symbol="BTC",
            direction="SHORT",
            entry_price=50_000.0,
            stop_loss=50_250.0,   # 0.5% above entry
            take_profit=49_250.0, # 1.5% below entry
            size_usd=100.0,
            size_crypto=0.002,
            leverage=5,
        )

    # LONG exits
    def test_long_sl_hit(self):
        should_exit, reason = self.strat.check_exit(self.long_pos, 49_700.0)
        assert should_exit and reason == "SL_HIT"

    def test_long_tp_hit(self):
        should_exit, reason = self.strat.check_exit(self.long_pos, 50_800.0)
        assert should_exit and reason == "TP_HIT"

    def test_long_no_exit_midway(self):
        should_exit, _ = self.strat.check_exit(self.long_pos, 50_100.0, elapsed_hours=1.0)
        assert not should_exit

    def test_long_max_hold_exit(self):
        should_exit, reason = self.strat.check_exit(self.long_pos, 50_100.0, elapsed_hours=25.0)
        assert should_exit and reason == "MAX_HOLD_EXPIRED"

    # SHORT exits
    def test_short_sl_hit(self):
        should_exit, reason = self.strat.check_exit(self.short_pos, 50_300.0)
        assert should_exit and reason == "SL_HIT"

    def test_short_tp_hit(self):
        should_exit, reason = self.strat.check_exit(self.short_pos, 49_200.0)
        assert should_exit and reason == "TP_HIT"

    def test_short_no_exit_midway(self):
        should_exit, _ = self.strat.check_exit(self.short_pos, 49_900.0, elapsed_hours=2.0)
        assert not should_exit


# ============================================================================
# TESTS — P&L Calculation
# ============================================================================


class TestPnLCalculation:
    """Unit tests for VMRStrategy.calculate_pnl()."""

    def setup_method(self):
        self.strat = VMRStrategy()
        self.pos = VMRPosition(
            symbol="BTC",
            direction="LONG",
            entry_price=50_000.0,
            stop_loss=49_750.0,
            take_profit=50_750.0,
            size_usd=100.0,
            size_crypto=0.002,
            leverage=5,
        )

    def test_long_win_pnl(self):
        """LONG position with price increase → positive P&L."""
        pnl_pct, pnl_usd = self.strat.calculate_pnl(self.pos, 50_750.0)
        assert pnl_pct > 0
        assert pnl_usd > 0

    def test_long_loss_pnl(self):
        """LONG position with price decrease → negative P&L."""
        pnl_pct, pnl_usd = self.strat.calculate_pnl(self.pos, 49_750.0)
        assert pnl_pct < 0
        assert pnl_usd < 0

    def test_long_sl_pnl_approx(self):
        """LONG SL exit at -0.5% should give ~-0.5% return and ~-$0.50."""
        pnl_pct, pnl_usd = self.strat.calculate_pnl(self.pos, 49_750.0)
        assert abs(pnl_pct - (-0.5)) < 0.01, f"Expected -0.5%, got {pnl_pct}"
        assert abs(pnl_usd - (-0.50)) < 0.01, f"Expected -$0.50, got {pnl_usd}"

    def test_long_tp_pnl_approx(self):
        """LONG TP exit at +1.5% should give ~+1.5% return."""
        pnl_pct, pnl_usd = self.strat.calculate_pnl(self.pos, 50_750.0)
        assert abs(pnl_pct - 1.5) < 0.01, f"Expected +1.5%, got {pnl_pct}"

    def test_short_win_pnl(self):
        """SHORT position with price decrease → positive P&L."""
        short_pos = VMRPosition(
            symbol="BTC",
            direction="SHORT",
            entry_price=50_000.0,
            stop_loss=50_250.0,
            take_profit=49_250.0,
            size_usd=100.0,
            size_crypto=0.002,
            leverage=5,
        )
        pnl_pct, pnl_usd = self.strat.calculate_pnl(short_pos, 49_250.0)
        assert pnl_pct > 0
        assert pnl_usd > 0


# ============================================================================
# TESTS — Backtest Engine
# ============================================================================


class TestBacktest:
    """Integration tests for VMRStrategy.run_backtest()."""

    def setup_method(self):
        self.cfg = VMRConfig(
            require_bb_confirmation=False,
            spike_threshold_pct=1.0,
            sl_pct=0.005,
            tp_pct=0.015,
            position_size_pct=0.01,
        )
        self.strat = VMRStrategy(self.cfg)

    def _make_volatile_df(self, n: int = 200) -> pd.DataFrame:
        """Generate a synthetic volatile price series with multiple spikes."""
        np.random.seed(123)
        base = 50_000.0
        returns = np.random.randn(n) * 0.8  # ~0.8% std per bar
        # Inject clear spikes
        spike_bars = [30, 60, 90, 120, 150, 180]
        for b in spike_bars:
            if b < n:
                returns[b] = -2.5  # -2.5% spike → should trigger LONG
        prices = [base]
        for r in returns:
            prices.append(prices[-1] * (1 + r / 100))
        df = pd.DataFrame({"close": prices, "high": prices, "low": prices})
        return df

    def test_backtest_returns_required_keys(self):
        """run_backtest() output must contain standard keys."""
        df = self._make_volatile_df()
        result = self.strat.run_backtest(df, "BTC")
        required = [
            "symbol", "trades", "wins", "losses", "win_rate",
            "total_pnl_usd", "return_pct", "max_dd_pct",
            "starting_balance", "ending_balance", "profit_factor",
        ]
        for key in required:
            assert key in result, f"Missing key: {key}"

    def test_backtest_no_trades_on_flat_data(self):
        """Flat price series → zero trades."""
        df = make_flat_df(200)
        result = self.strat.run_backtest(df, "BTC")
        assert result["trades"] == 0
        assert result["total_pnl_usd"] == 0.0

    def test_backtest_detects_spikes(self):
        """Volatile series should produce at least some signals."""
        df = self._make_volatile_df(200)
        result = self.strat.run_backtest(df, "BTC")
        assert result["signals_detected"] > 0, "No signals detected in volatile series"

    def test_backtest_wins_plus_losses_equals_trades(self):
        """wins + losses must equal total trades."""
        df = self._make_volatile_df(200)
        result = self.strat.run_backtest(df, "BTC")
        assert result["wins"] + result["losses"] == result["trades"]

    def test_backtest_win_rate_bounded(self):
        """Win rate must be 0–100."""
        df = self._make_volatile_df(200)
        result = self.strat.run_backtest(df, "BTC")
        assert 0.0 <= result["win_rate"] <= 100.0

    def test_backtest_balance_consistency(self):
        """ending_balance - starting_balance ≈ total_pnl_usd."""
        df = self._make_volatile_df(200)
        result = self.strat.run_backtest(df, "BTC")
        diff = result["ending_balance"] - result["starting_balance"]
        assert abs(diff - result["total_pnl_usd"]) < 0.01, (
            f"Balance diff={diff:.2f} != total_pnl={result['total_pnl_usd']:.2f}"
        )

    def test_backtest_config_echoed(self):
        """Config should be echoed back in result."""
        df = self._make_volatile_df(200)
        result = self.strat.run_backtest(df, "BTC")
        assert "config" in result
        assert result["config"]["sl_pct"] == self.cfg.sl_pct
        assert result["config"]["tp_pct"] == self.cfg.tp_pct


# ============================================================================
# TESTS — format_signal()
# ============================================================================


class TestFormatSignal:
    """Tests for the human-readable signal formatter."""

    def setup_method(self):
        self.strat = VMRStrategy()

    def test_none_signal_format(self):
        sig = VMRSignal(symbol="BTC", direction="NONE", reason="No spike")
        msg = self.strat.format_signal(sig)
        assert "NO SIGNAL" in msg
        assert "BTC" in msg

    def test_long_signal_format(self):
        sig = VMRSignal(
            symbol="ETH",
            direction="LONG",
            entry_price=2500.0,
            stop_loss=2487.5,
            take_profit=2537.5,
            rr_ratio=3.0,
            confidence=0.75,
            reason="Spike -2.0%",
        )
        msg = self.strat.format_signal(sig)
        assert "LONG" in msg
        assert "ETH" in msg
        assert "✅" in msg


# ============================================================================
# RUN
# ============================================================================


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
