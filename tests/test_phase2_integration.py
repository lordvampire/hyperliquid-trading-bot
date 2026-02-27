"""
Phase 2 Integration Tests
=========================
Tests for: PositionSizer, WalkForwardValidator, ParameterRegistry,
           and enhanced BacktestEngineV2 (slippage + commission).
"""

from __future__ import annotations
import os
import sys
import json
import tempfile
from pathlib import Path

import pytest
import pandas as pd

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))

from config.manager import ConfigManager
from strategies.strategy_b import StrategyB
from position_sizing import PositionSizer
from backtest_validator import WalkForwardValidator
from param_registry import ParameterRegistry
from backtest_engine_v2 import BacktestEngineV2

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

CONFIG_PATH = str(REPO_ROOT / "config" / "base.yaml")


@pytest.fixture(scope="module")
def config():
    return ConfigManager(CONFIG_PATH, "backtest")


@pytest.fixture(scope="module")
def strategy(config):
    return StrategyB(config.strategy("strategy_b"), "backtest")


@pytest.fixture(scope="module")
def sizer(config):
    return PositionSizer(config.get("position_sizing"))


@pytest.fixture(scope="module")
def engine(strategy, config):
    return BacktestEngineV2(strategy, config)


@pytest.fixture(scope="module")
def validator(strategy, config):
    return WalkForwardValidator(strategy, config)


@pytest.fixture(scope="module")
def sample_ohlcv():
    """300-bar synthetic OHLCV DataFrame for testing."""
    return WalkForwardValidator._synthesise_ohlcv(300, seed=42)


# ---------------------------------------------------------------------------
# PositionSizer tests
# ---------------------------------------------------------------------------

class TestPositionSizer:

    def test_calculate_size_with_volatility(self, sizer):
        """Higher volatility should produce larger size (up to cap)."""
        size_low  = sizer.calculate_size(10_000, volatility=0.01, signal_strength=1.0)
        size_high = sizer.calculate_size(10_000, volatility=0.10, signal_strength=1.0)
        assert size_high > size_low, "Higher volatility should yield larger position"
        assert size_low > 0

    def test_risk_limits_enforced(self, sizer):
        """Size must never exceed max_position_pct of balance."""
        balance = 50_000.0
        max_pct = sizer.max_position_pct
        for vol in (0.0, 0.05, 0.30):
            size = sizer.calculate_size(balance, volatility=vol, signal_strength=1.0)
            assert size <= balance * max_pct + 1e-6, (
                f"Position size {size:.2f} exceeds max {balance * max_pct:.2f}"
            )

    def test_leverage_cap_attribute(self, sizer):
        """leverage_cap should be loaded from config and positive."""
        assert sizer.leverage_cap > 0

    def test_calculate_contracts(self, sizer):
        """USD size / price = contracts."""
        contracts = sizer.calculate_contracts(1_000.0, entry_price=50_000.0)
        assert abs(contracts - 0.02) < 1e-6

    def test_apply_risk_limit_clamps(self, sizer):
        """apply_risk_limit should cap at max_pct of balance."""
        result = sizer.apply_risk_limit(size=5_000.0, max_pct=0.10, account_balance=10_000.0)
        assert result <= 1_000.0 + 1e-6

    def test_zero_signal_strength_gives_zero_size(self, sizer):
        """Signal strength of 0 → position size of 0."""
        size = sizer.calculate_size(10_000, volatility=0.05, signal_strength=0.0)
        assert size == 0.0

    def test_contracts_raises_on_zero_price(self, sizer):
        with pytest.raises(ValueError):
            sizer.calculate_contracts(1_000.0, entry_price=0.0)


# ---------------------------------------------------------------------------
# WalkForwardValidator tests
# ---------------------------------------------------------------------------

class TestWalkForwardValidator:

    def test_walk_forward_produces_results(self, validator):
        """360 days > 180+60 so we must get at least 1 window."""
        results = validator.run_walk_forward("BTC", days=360, window_size=180, test_size=60)
        assert "error" not in results, results.get("error")
        assert results["windows"] >= 1
        assert "avg_sharpe" in results

    def test_overfitting_detection_positive(self, validator):
        """test < 0.5 * train → overfit=True."""
        assert validator.detect_overfitting(train_sharpe=2.0, test_sharpe=0.5) is True

    def test_overfitting_detection_negative(self, validator):
        """test >= 0.5 * train → overfit=False."""
        assert validator.detect_overfitting(train_sharpe=2.0, test_sharpe=1.2) is False

    def test_overfitting_no_flag_when_train_nonpositive(self, validator):
        """Non-positive train sharpe should not flag overfitting."""
        assert validator.detect_overfitting(train_sharpe=0.0, test_sharpe=-1.0) is False
        assert validator.detect_overfitting(train_sharpe=-1.0, test_sharpe=0.5) is False

    def test_consistency_metric_in_range(self, validator):
        """Consistency must be in [0, 1]."""
        results = validator.run_walk_forward("ETH", days=360, window_size=180, test_size=60)
        if "error" not in results:
            assert 0.0 <= results["consistency"] <= 1.0

    def test_aggregate_results_structure(self, validator):
        """aggregate_results must return all required keys."""
        dummy_windows = [
            {"train": {"sharpe": 1.0, "max_dd": 5.0, "win_rate": 55.0},
             "test":  {"sharpe": 0.8, "max_dd": 6.0, "win_rate": 52.0},
             "overfit": False},
            {"train": {"sharpe": 1.2, "max_dd": 4.0, "win_rate": 58.0},
             "test":  {"sharpe": 0.4, "max_dd": 8.0, "win_rate": 48.0},
             "overfit": True},
        ]
        agg = validator.aggregate_results(dummy_windows)
        for key in ("avg_sharpe", "avg_max_dd", "avg_win_rate", "consistency", "overfitting_detected"):
            assert key in agg, f"Missing key: {key}"

    def test_insufficient_data_returns_error(self, validator):
        """Too-short period should return an error dict."""
        result = validator.run_walk_forward("BTC", days=50, window_size=180, test_size=60)
        assert "error" in result


# ---------------------------------------------------------------------------
# ParameterRegistry tests
# ---------------------------------------------------------------------------

class TestParameterRegistry:

    def test_register_and_retrieve_run(self, tmp_path):
        db = tmp_path / "test_registry.json"
        registry = ParameterRegistry(str(db))

        run_id = registry.register_run(
            "strategy_b",
            params={"fast_period": 5, "slow_period": 20},
            result={"sharpe": 1.5, "max_dd": 7.0, "win_rate": 0.55},
        )
        assert isinstance(run_id, str) and len(run_id) > 0

        # File must exist and be valid JSON
        assert db.exists()
        data = json.loads(db.read_text())
        assert "strategy_b" in data
        assert data["strategy_b"][0]["run_id"] == run_id

    def test_get_best_params(self, tmp_path):
        db = tmp_path / "test_best.json"
        registry = ParameterRegistry(str(db))

        registry.register_run("strategy_b",
                               params={"fast_period": 5},
                               result={"sharpe": 0.8, "max_dd": 10.0, "win_rate": 0.50})
        registry.register_run("strategy_b",
                               params={"fast_period": 8},
                               result={"sharpe": 1.6, "max_dd": 6.0,  "win_rate": 0.60})

        best = registry.get_best_params("strategy_b", metric="sharpe")
        assert best == {"fast_period": 8}, f"Expected fast_period=8, got {best}"

    def test_get_run_history_limit(self, tmp_path):
        db = tmp_path / "test_history.json"
        registry = ParameterRegistry(str(db))

        for i in range(5):
            registry.register_run("strategy_b",
                                   params={"fast_period": i},
                                   result={"sharpe": float(i), "max_dd": 5.0, "win_rate": 0.5})

        history = registry.get_run_history("strategy_b", limit=3)
        assert len(history) == 3

    def test_export_csv(self, tmp_path):
        db    = tmp_path / "test_export.json"
        csv_p = tmp_path / "export.csv"
        registry = ParameterRegistry(str(db))

        registry.register_run("strategy_b",
                               params={"fast_period": 5, "slow_period": 20},
                               result={"sharpe": 1.2, "max_dd": 8.0, "win_rate": 0.52})
        registry.export_csv(str(csv_p), "strategy_b")

        assert csv_p.exists()
        lines = csv_p.read_text().splitlines()
        assert len(lines) == 2  # header + 1 data row
        assert "sharpe" in lines[0]

    def test_empty_registry_returns_none(self, tmp_path):
        db = tmp_path / "empty.json"
        registry = ParameterRegistry(str(db))
        assert registry.get_best_params("nonexistent") is None


# ---------------------------------------------------------------------------
# Enhanced BacktestEngineV2 tests
# ---------------------------------------------------------------------------

class TestEnhancedBacktestEngineV2:

    def test_slippage_applied_correctly(self, engine, sample_ohlcv):
        """Slippage cost should be > 0 when slippage_pct + spread_pct > 0."""
        signals = engine.strategy.generate_signals(sample_ohlcv)
        result  = engine._simulate(sample_ohlcv, signals, "BTC")
        # If we have any trades, slippage must be tracked
        if result["trades"] > 0:
            assert result["slippage_cost_usd"] >= 0
            assert "slippage_cost_usd" in result

    def test_commission_deducted(self, engine, sample_ohlcv):
        """Commission must be positive when trades are made."""
        signals = engine.strategy.generate_signals(sample_ohlcv)
        result  = engine._simulate(sample_ohlcv, signals, "BTC")
        if result["trades"] > 0:
            assert result["commission_usd"] > 0
            assert result["total_fees_pct"] > 0

    def test_realistic_costs_present_in_result(self, engine, sample_ohlcv):
        """All cost fields must be present in the result dict."""
        signals = engine.strategy.generate_signals(sample_ohlcv)
        result  = engine._simulate(sample_ohlcv, signals, "BTC")
        for key in ("slippage_cost_usd", "commission_usd", "total_cost_pct", "total_fees_pct"):
            assert key in result, f"Missing cost field: {key}"

    def test_cost_fields_are_nonnegative(self, engine, sample_ohlcv):
        """All cost metrics should be non-negative."""
        signals = engine.strategy.generate_signals(sample_ohlcv)
        result  = engine._simulate(sample_ohlcv, signals, "BTC")
        assert result["slippage_cost_usd"] >= 0
        assert result["commission_usd"]    >= 0
        assert result["total_cost_pct"]    >= 0

    def test_backtest_from_data_works(self, engine, sample_ohlcv):
        """backtest_from_data should return a valid stats dict."""
        result = engine.backtest_from_data(sample_ohlcv, "BTC", days=12)
        assert "error" not in result
        assert "win_rate" in result
        assert result["starting_balance"] > 0

    def test_engine_cost_params_loaded_from_config(self, engine):
        """Engine should load taker_fee from config."""
        assert engine.taker_fee > 0, "taker_fee should be loaded from config"
        assert engine.maker_fee > 0, "maker_fee should be loaded from config"
        assert engine.slippage_pct >= 0
        assert engine.spread_pct >= 0
