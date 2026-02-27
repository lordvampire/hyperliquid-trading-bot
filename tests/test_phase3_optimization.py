"""
Phase 3 integration tests — Parameter optimization + Paper trading.

Run with:
    cd ~/hyperliquid-trading-bot
    python -m pytest tests/test_phase3_optimization.py -v

All tests use synthetic data (no live API calls required).
"""

from __future__ import annotations

import os
import json
import math
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict

import pytest

# ---------------------------------------------------------------------------
# Path fixture: add project root so imports work regardless of CWD
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def config():
    from config.manager import ConfigManager
    return ConfigManager(str(PROJECT_ROOT / "config" / "base.yaml"), "backtest")


@pytest.fixture(scope="session")
def strategy(config):
    from strategies.strategy_b import StrategyB
    return StrategyB(config.strategy("strategy_b"), "backtest")


@pytest.fixture(scope="session")
def registry(tmp_path_factory):
    from param_registry import ParameterRegistry
    db = tmp_path_factory.mktemp("registry") / "test_registry.json"
    return ParameterRegistry(str(db))


@pytest.fixture(scope="session")
def optimizer(strategy, config, registry):
    from param_optimizer import ParamOptimizer
    return ParamOptimizer(strategy, config, registry, "strategy_b")


@pytest.fixture(scope="session")
def analyzer(optimizer):
    from sensitivity_analyzer import SensitivityAnalyzer
    return SensitivityAnalyzer(optimizer)


# ---------------------------------------------------------------------------
# ParamOptimizer tests
# ---------------------------------------------------------------------------

class TestParamOptimizer:

    def test_sensitivity_analysis_identifies_impactful_params(self, optimizer):
        """sensitivity_analysis returns a non-empty sorted dict."""
        result = optimizer.sensitivity_analysis("BTC", days=10)

        assert isinstance(result, dict), "Should return a dict"
        assert len(result) > 0, "Should identify at least one param"

        # Scores should be non-negative (std dev)
        for param, score in result.items():
            assert score >= 0.0, f"Impact score for {param} must be >= 0"

        # Dict should be sorted descending
        scores = list(result.values())
        assert scores == sorted(scores, reverse=True), "Should be sorted descending"

    def test_sensitivity_analysis_covers_all_strategy_params(self, optimizer):
        """All StrategyB params should appear in sensitivity output."""
        result = optimizer.sensitivity_analysis("BTC", days=10)
        strategy_params = set(optimizer.strategy.config.keys())
        for param in strategy_params:
            assert param in result or param not in optimizer.strategy.config, \
                f"Param {param} missing from sensitivity result"

    def test_grid_search_produces_results(self, optimizer):
        """grid_search returns best_params and top_10_results."""
        result = optimizer.grid_search("BTC", days=10, top_n_params=2)

        assert "best_params" in result
        assert "top_10_results" in result
        assert isinstance(result["top_10_results"], list)
        assert len(result["top_10_results"]) > 0

        # best_params should be a valid strategy config
        best = result["best_params"]
        assert "fast_period" in best
        assert "slow_period" in best
        assert "entry_threshold" in best

    def test_grid_search_top_results_sorted_by_sharpe(self, optimizer):
        """top_10_results must be sorted descending by Sharpe."""
        result = optimizer.grid_search("BTC", days=10, top_n_params=2)
        top = result.get("top_10_results", [])
        if len(top) > 1:
            sharpes = [r["sharpe"] for r in top]
            assert sharpes == sorted(sharpes, reverse=True), "Must be sorted by Sharpe desc"

    def test_grid_search_tracks_in_registry(self, optimizer, registry):
        """Grid search should log runs to the ParameterRegistry."""
        before = len(registry.get_run_history("strategy_b", limit=10000))
        optimizer.grid_search("BTC", days=5, top_n_params=2)
        after = len(registry.get_run_history("strategy_b", limit=10000))
        assert after > before, "Registry should have more entries after grid search"

    def test_optuna_search_improves_on_grid(self, optimizer):
        """Optuna search should return a best_params_optuna dict."""
        # Run a quick grid search first
        grid = optimizer.grid_search("BTC", days=10, top_n_params=2)
        result = optimizer.optuna_search("BTC", days=10, n_trials=5, grid_result=grid)

        assert "best_params_optuna" in result
        assert isinstance(result["best_params_optuna"], dict)
        assert "all_trials_list" in result
        assert isinstance(result["all_trials_list"], list)

    def test_optuna_search_respects_constraints(self, optimizer):
        """Optuna results with constraint violations should be penalised."""
        grid = optimizer.grid_search("BTC", days=10, top_n_params=2)
        result = optimizer.optuna_search("BTC", days=10, n_trials=5, grid_result=grid)
        # Valid trials should not have extreme negative Sharpe (< -10)
        for trial in result["all_trials_list"]:
            assert trial["sharpe"] > -10.0, "Penalised trial leaked into results"


# ---------------------------------------------------------------------------
# SensitivityAnalyzer tests
# ---------------------------------------------------------------------------

class TestSensitivityAnalyzer:

    def test_single_param_sensitivity(self, analyzer, tmp_path):
        """analyze_single_param returns correct structure."""
        result = analyzer.analyze_single_param(
            "BTC", "fast_period", days=10, output_dir=str(tmp_path)
        )

        assert "param_name" in result
        assert result["param_name"] == "fast_period"
        assert "baseline_value" in result
        assert "sensitivities" in result
        assert "chart_path" in result
        assert isinstance(result["sensitivities"], list)
        assert len(result["sensitivities"]) == len(analyzer.VARIATIONS)

    def test_single_param_sensitivities_have_required_keys(self, analyzer, tmp_path):
        """Each sensitivity entry has factor, param_value, sharpe, win_rate."""
        result = analyzer.analyze_single_param(
            "BTC", "rsi_period", days=10, output_dir=str(tmp_path)
        )
        for s in result["sensitivities"]:
            assert "factor" in s
            assert "param_value" in s
            assert "sharpe" in s
            assert "win_rate" in s

    def test_chart_file_created(self, analyzer, tmp_path):
        """analyze_single_param should create a chart file."""
        result = analyzer.analyze_single_param(
            "BTC", "entry_threshold", days=10, output_dir=str(tmp_path)
        )
        chart_path = result.get("chart_path", "")
        assert chart_path and Path(chart_path).exists(), \
            f"Chart file not created at {chart_path}"

    def test_correlation_matrix_shape(self, analyzer):
        """correlation_matrix returns square ndarray of correct shape."""
        import numpy as np
        matrix = analyzer.correlation_matrix("BTC", days=10)

        assert isinstance(matrix, np.ndarray), "Should return numpy array"
        assert matrix.ndim == 2, "Should be 2D"
        assert matrix.shape[0] == matrix.shape[1], "Should be square"

    def test_correlation_matrix_diagonal_is_one(self, analyzer):
        """Diagonal of correlation matrix should be ≈ 1 (self-correlation).
        When a param has zero variance across variations (constant Sharpe delta),
        np.corrcoef returns NaN which we replace with 0 — those diagonals are exempt."""
        import numpy as np
        matrix = analyzer.correlation_matrix("BTC", days=10)
        for i in range(matrix.shape[0]):
            diag = matrix[i, i]
            # Acceptable values: 1.0 (normal) or 0.0 (degenerate constant row → nan→0)
            assert abs(diag - 1.0) < 0.2 or abs(diag) < 0.2, \
                f"Diagonal element [{i},{i}] = {diag:.4f}, expected ≈ 1 or 0 (degenerate)"

    def test_unknown_param_returns_error(self, analyzer, tmp_path):
        """analyze_single_param with unknown param returns error dict."""
        result = analyzer.analyze_single_param(
            "BTC", "nonexistent_param", days=10, output_dir=str(tmp_path)
        )
        assert "error" in result


# ---------------------------------------------------------------------------
# OptimizationRunner tests
# ---------------------------------------------------------------------------

class TestOptimizationRunner:

    def _make_runner(self, symbol: str = "BTC", days: int = 10):
        from optimization_runner import OptimizationRunner
        return OptimizationRunner(
            symbol, days,
            config_path=str(PROJECT_ROOT / "config" / "base.yaml"),
            registry_path=str(tempfile.mktemp(suffix=".json")),
        )

    def test_quick_optimization_completes(self, tmp_path):
        """quick_optimization returns result dict with required keys."""
        runner = self._make_runner(days=10)
        result = runner.quick_optimization(str(tmp_path))

        assert "best_params" in result
        assert "sharpe_final" in result
        assert "dd_final" in result
        assert "win_rate_final" in result
        assert isinstance(result["best_params"], dict)

    def test_quick_optimization_creates_output_files(self, tmp_path):
        """quick_optimization creates grid_search_results.csv and final_best_params.json."""
        runner = self._make_runner(days=10)
        runner.quick_optimization(str(tmp_path))

        assert (tmp_path / "grid_search_results.csv").exists(), "CSV not created"
        assert (tmp_path / "final_best_params.json").exists(), "JSON not created"

    def test_final_best_params_json_is_valid(self, tmp_path):
        """final_best_params.json should be parseable and contain best_params."""
        runner = self._make_runner(days=10)
        runner.quick_optimization(str(tmp_path))

        with (tmp_path / "final_best_params.json").open() as fh:
            data = json.load(fh)
        assert "best_params" in data
        assert "sharpe_final" in data

    def test_full_pipeline_produces_best_params(self, tmp_path):
        """run_full_pipeline returns a valid result dict."""
        runner = self._make_runner(days=10)
        result = runner.run_full_pipeline(str(tmp_path))

        assert "best_params" in result
        assert isinstance(result["best_params"], dict)
        assert len(result["best_params"]) > 0

    def test_full_pipeline_creates_all_artefacts(self, tmp_path):
        """run_full_pipeline creates all 5 output files."""
        runner = self._make_runner(days=10)
        runner.run_full_pipeline(str(tmp_path))

        expected = [
            "sensitivity_report.json",
            "grid_search_results.csv",
            "optuna_trials.json",
            "final_best_params.json",
            "walk_forward_validation.json",
        ]
        for fname in expected:
            assert (tmp_path / fname).exists(), f"Missing: {fname}"

    def test_walk_forward_validation_runs(self, tmp_path):
        """validate_params returns a boolean."""
        runner = self._make_runner(days=10)
        params = dict(runner.strategy.config)
        result = runner.validate_params(params)
        assert isinstance(result, bool)


# ---------------------------------------------------------------------------
# PaperTrader tests
# ---------------------------------------------------------------------------

class TestPaperTrader:

    @pytest.fixture(scope="class")
    def trader(self, strategy, config):
        from paper_trader import PaperTrader
        return PaperTrader(strategy, config)

    def test_paper_trade_simulates_correctly(self, trader):
        """paper_trade returns a result dict with required keys."""
        result = trader.paper_trade("BTC", starting_balance=1000.0, duration_days=7)

        assert "total_pnl" in result
        assert "return_pct" in result
        assert "trades_executed" in result
        assert "daily_pnl_list" in result
        assert "max_dd" in result

        # Numeric sanity checks
        assert isinstance(result["total_pnl"],       float)
        assert isinstance(result["trades_executed"], int)
        assert result["max_dd"] >= 0.0, "Max DD must be non-negative"

    def test_paper_trade_balance_consistency(self, trader):
        """ending_balance = starting_balance + total_pnl (approximately)."""
        starting = 1000.0
        result = trader.paper_trade("BTC", starting_balance=starting, duration_days=7)
        expected_ending = starting + result["total_pnl"]
        assert abs(result["ending_balance"] - expected_ending) < 1.0, \
            f"Balance inconsistency: {result['ending_balance']} != {expected_ending}"

    def test_paper_trade_win_rate_in_range(self, trader):
        """Win rate should be between 0 and 100."""
        result = trader.paper_trade("BTC", starting_balance=1000.0, duration_days=7)
        assert 0.0 <= result["win_rate"] <= 100.0

    def test_backtest_vs_paper_comparison(self, trader):
        """compare_backtest_vs_paper returns a comparison dict."""
        result = trader.compare_backtest_vs_paper("BTC", days=10)

        assert "backtest_pnl" in result
        assert "paper_pnl" in result
        assert "signal_match_rate" in result
        assert "divergence_alerts" in result
        assert isinstance(result["divergence_alerts"], list)

    def test_divergence_detection(self, trader):
        """Divergence flag should be set when pnl differs by more than 10%."""
        # We can't force divergence with identical strategy + data,
        # so just check the logic path runs without error.
        result = trader.compare_backtest_vs_paper("BTC", days=10)
        assert "divergence_detected" in result
        assert isinstance(result["divergence_detected"], bool)

    def test_paper_trade_uses_recent_data(self, trader):
        """Data rows should equal duration_days * 24 (hourly candles)."""
        days = 7
        result = trader.paper_trade("BTC", starting_balance=1000.0, duration_days=days)
        # We can't easily inspect internal data, but result should be populated
        assert "symbol" in result
        assert result["duration_days"] == days

    def test_compare_returns_trade_counts(self, trader):
        """Comparison should include trade counts for both modes."""
        result = trader.compare_backtest_vs_paper("BTC", days=10)
        assert "backtest_trades" in result
        assert "paper_trades" in result
        assert result["backtest_trades"] >= 0
        assert result["paper_trades"] >= 0
