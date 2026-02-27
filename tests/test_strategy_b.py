"""Unit tests for StrategyB (Phase 1 refactor)."""

from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
import pandas as pd
import numpy as np

from strategies.base import Signal, StrategyBase
from strategies.strategy_b import StrategyB
from config.manager import ConfigManager


# ------------------------------------------------------------------
# Shared fixtures
# ------------------------------------------------------------------

VALID_CONFIG = {
    "fast_period": 5,
    "slow_period": 20,
    "rsi_period": 14,
    "momentum_weight": 0.50,
    "rsi_weight": 0.30,
    "volume_weight": 0.20,
    "entry_threshold": 0.40,
    "exit_threshold": 0.15,
    "stop_pct": 0.02,
    "tp_pct": 0.04,
}


def make_mock_df(n: int = 60, trend: float = 0.5) -> pd.DataFrame:
    """Return a deterministic OHLCV DataFrame."""
    np.random.seed(42)
    close = 100.0
    rows = []
    for _ in range(n):
        close = close * (1 + np.random.normal(trend / 1000, 0.005))
        rows.append({
            "open": close * 0.999,
            "high": close * 1.005,
            "low":  close * 0.995,
            "close": close,
            "volume": np.random.uniform(800, 1200),
        })
    return pd.DataFrame(rows)


# ------------------------------------------------------------------
# 1. Initialisation
# ------------------------------------------------------------------

class TestStrategyBInit:
    def test_init_with_valid_config(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        assert strat is not None
        assert strat.mode == "backtest"

    def test_init_stores_config(self):
        strat = StrategyB(VALID_CONFIG, "paper")
        assert strat.config["fast_period"] == 5

    def test_init_missing_param_raises(self):
        bad_cfg = {k: v for k, v in VALID_CONFIG.items() if k != "entry_threshold"}
        with pytest.raises(ValueError, match="Missing required config keys"):
            StrategyB(bad_cfg, "backtest")

    def test_init_empty_config_raises(self):
        with pytest.raises(ValueError):
            StrategyB({}, "backtest")


# ------------------------------------------------------------------
# 2. required_params()
# ------------------------------------------------------------------

class TestRequiredParams:
    def test_returns_list(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        assert isinstance(strat.required_params(), list)

    def test_contains_expected_keys(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        rp = strat.required_params()
        for key in ["fast_period", "entry_threshold", "stop_pct", "tp_pct"]:
            assert key in rp, f"{key} missing from required_params()"

    def test_all_params_in_valid_config(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        for key in strat.required_params():
            assert key in VALID_CONFIG


# ------------------------------------------------------------------
# 3. get_params()
# ------------------------------------------------------------------

class TestGetParams:
    def test_returns_dict(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        assert isinstance(strat.get_params(), dict)

    def test_matches_input_config(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        params = strat.get_params()
        assert params["fast_period"] == 5
        assert params["entry_threshold"] == 0.40


# ------------------------------------------------------------------
# 4. generate_signals()
# ------------------------------------------------------------------

class TestGenerateSignals:
    def test_returns_list(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        df = make_mock_df(60)
        sigs = strat.generate_signals(df)
        assert isinstance(sigs, list)

    def test_all_items_are_signal_instances(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        df = make_mock_df(60)
        sigs = strat.generate_signals(df)
        assert all(isinstance(s, Signal) for s in sigs)

    def test_signal_fields_populated(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        df = make_mock_df(60)
        sigs = strat.generate_signals(df)
        for s in sigs:
            assert s.direction in ("LONG", "SHORT", "HOLD")
            assert 0.0 <= s.strength <= 1.0
            assert isinstance(s.metadata, dict)
            assert "composite_score" in s.metadata
            assert "bar_index" in s.metadata

    def test_stop_loss_take_profit_set_for_long(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        df = make_mock_df(60)
        sigs = strat.generate_signals(df)
        long_sigs = [s for s in sigs if s.direction == "LONG"]
        if long_sigs:
            s = long_sigs[0]
            assert s.stop_loss > 0
            assert s.take_profit > s.stop_loss

    def test_empty_df_returns_empty_list(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        sigs = strat.generate_signals(pd.DataFrame())
        assert sigs == []

    def test_insufficient_data_returns_empty(self):
        strat = StrategyB(VALID_CONFIG, "backtest")
        df = make_mock_df(5)
        sigs = strat.generate_signals(df)
        assert sigs == []


# ------------------------------------------------------------------
# 5. ConfigManager integration
# ------------------------------------------------------------------

class TestConfigManagerIntegration:
    def test_load_base_yaml(self):
        cfg = ConfigManager("config/base.yaml", "backtest")
        assert cfg.strategy("strategy_b")["entry_threshold"] == 0.40

    def test_strategy_returns_dict(self):
        cfg = ConfigManager("config/base.yaml", "backtest")
        strat_cfg = cfg.strategy("strategy_b")
        assert isinstance(strat_cfg, dict)

    def test_strategy_b_from_config(self):
        cfg = ConfigManager("config/base.yaml", "backtest")
        strat = StrategyB(cfg.strategy("strategy_b"), "backtest")
        assert "fast_period" in strat.get_params()

    def test_missing_strategy_raises(self):
        cfg = ConfigManager("config/base.yaml", "backtest")
        with pytest.raises(KeyError):
            cfg.strategy("nonexistent_strategy")

    def test_dot_notation_get(self):
        cfg = ConfigManager("config/base.yaml", "backtest")
        slippage = cfg.get("backtest.slippage_pct")
        assert slippage == 0.08


# ------------------------------------------------------------------
# Standalone runner
# ------------------------------------------------------------------

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
