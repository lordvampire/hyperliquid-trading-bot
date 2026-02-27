"""
ParamOptimizer — Sensitivity analysis, grid search, and Bayesian (Optuna) optimization.

Workflow:
    1. sensitivity_analysis  → identifies which params matter most
    2. grid_search           → coarse 7-value scan across top-N params
    3. optuna_search         → Bayesian refinement around grid-search results

All results are tracked in a ParameterRegistry.

Usage:
    from config.manager import ConfigManager
    from strategies.strategy_b import StrategyB
    from param_registry import ParameterRegistry
    from param_optimizer import ParamOptimizer

    config   = ConfigManager("config/base.yaml", "backtest")
    strategy = StrategyB(config.strategy("strategy_b"), "backtest")
    registry = ParameterRegistry("param_history.json")
    optimizer = ParamOptimizer(strategy, config, registry)

    sensitivity = optimizer.sensitivity_analysis("BTC", days=30)
    grid_result = optimizer.grid_search("BTC", days=30)
    optuna_result = optimizer.optuna_search("BTC", days=30, n_trials=50)
"""

from __future__ import annotations

import copy
import itertools
import logging
import math
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from strategies.base import StrategyBase
from config.manager import ConfigManager
from backtest_engine_v2 import BacktestEngineV2
from backtest_validator import WalkForwardValidator
from param_registry import ParameterRegistry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Param bounds — defines valid ranges for each StrategyB parameter
# ---------------------------------------------------------------------------
PARAM_BOUNDS: Dict[str, Tuple[float, float]] = {
    "fast_period":      (2,    15),
    "slow_period":      (10,   50),
    "rsi_period":       (7,    28),
    "momentum_weight":  (0.1,  0.9),
    "rsi_weight":       (0.1,  0.9),
    "volume_weight":    (0.05, 0.5),
    "entry_threshold":  (0.1,  0.7),
    "exit_threshold":   (0.05, 0.4),
    "stop_pct":         (0.005, 0.05),
    "tp_pct":           (0.01,  0.10),
}

# Integer params (must be rounded to int before passing to strategy)
INTEGER_PARAMS = {"fast_period", "slow_period", "rsi_period"}


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


def _make_strategy(base_strategy: StrategyBase, params: Dict[str, Any]) -> StrategyBase:
    """Clone the strategy with a new param dict."""
    new_config = {**base_strategy.config, **params}
    return base_strategy.__class__(new_config, base_strategy.mode)


def _quick_sharpe(stats: Dict[str, Any]) -> float:
    """Derive a Sharpe proxy from backtest stats."""
    if "error" in stats:
        return -9.0
    ret = stats.get("return_pct", 0.0)
    dd  = stats.get("max_dd", 1.0) or 1.0
    return round(ret / dd, 4)


class ParamOptimizer:
    """Coordinate sensitivity analysis, grid search, and Optuna Bayesian search."""

    def __init__(
        self,
        strategy: StrategyBase,
        config: ConfigManager,
        registry: ParameterRegistry,
        strategy_name: str = "strategy_b",
    ):
        self.strategy      = strategy
        self.config        = config
        self.registry      = registry
        self.strategy_name = strategy_name
        self.engine        = BacktestEngineV2(strategy, config)

    # ------------------------------------------------------------------
    # 1. Sensitivity Analysis
    # ------------------------------------------------------------------

    def sensitivity_analysis(self, symbol: str, days: int) -> Dict[str, float]:
        """
        For each param: vary ±10%, ±20%, ±30% and score via backtest.
        Returns {param_name: impact_score} sorted descending by impact.
        """
        variations = self.config.get(
            "optimization.sensitivity_variations",
            [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3],
        )

        baseline_params = dict(self.strategy.config)
        data = self._load_data(symbol, days)
        if data is None:
            logger.error("[Sensitivity] No data available")
            return {}

        baseline_sharpe = self._eval_params(baseline_params, data, symbol, days)
        logger.info(f"[Sensitivity] Baseline Sharpe: {baseline_sharpe:.4f}")

        impact_scores: Dict[str, float] = {}

        for param in PARAM_BOUNDS:
            if param not in baseline_params:
                continue

            baseline_val = float(baseline_params[param])
            lo, hi = PARAM_BOUNDS[param]
            sharpes = []

            for factor in variations:
                new_val = _clamp(baseline_val * factor, lo, hi)
                if param in INTEGER_PARAMS:
                    new_val = max(1, round(new_val))

                test_params = {**baseline_params, param: new_val}
                sharpe = self._eval_params(test_params, data, symbol, days)
                sharpes.append(sharpe)

            # Impact = std dev of Sharpe across variations (sensitivity)
            if len(sharpes) > 1:
                mean = sum(sharpes) / len(sharpes)
                variance = sum((s - mean) ** 2 for s in sharpes) / len(sharpes)
                impact = math.sqrt(variance)
            else:
                impact = 0.0

            impact_scores[param] = round(impact, 6)
            logger.info(f"[Sensitivity] {param}: impact={impact:.4f}")

        # Sort by impact descending
        sorted_scores = dict(
            sorted(impact_scores.items(), key=lambda x: x[1], reverse=True)
        )
        return sorted_scores

    # ------------------------------------------------------------------
    # 2. Grid Search
    # ------------------------------------------------------------------

    def grid_search(
        self,
        symbol: str,
        days: int,
        top_n_params: int = 3,
    ) -> Dict[str, Any]:
        """
        Run coarse 7-point grid search over the top-N most impactful params.
        Returns {best_params, top_10_results_sorted_by_sharpe}.
        """
        n_values = int(
            self.config.get("optimization.grid_search_values_per_param", 7)
        )

        # Step 1: sensitivity to pick top params
        logger.info("[GridSearch] Running sensitivity analysis to pick top params...")
        sensitivity = self.sensitivity_analysis(symbol, days)
        top_params  = list(sensitivity.keys())[:top_n_params]
        logger.info(f"[GridSearch] Top {top_n_params} params: {top_params}")

        baseline_params = dict(self.strategy.config)
        data = self._load_data(symbol, days)
        if data is None:
            return {"error": "No data", "best_params": baseline_params, "top_10_results": []}

        # Build value grids for each top param
        param_grids: Dict[str, List[float]] = {}
        for param in top_params:
            baseline_val = float(baseline_params.get(param, 1.0))
            lo, hi = PARAM_BOUNDS.get(param, (baseline_val * 0.5, baseline_val * 2.0))
            std = (hi - lo) / 6.0  # approximate 1-sigma

            # 7 values: min, -3sd, -sd, baseline, +sd, +3sd, max
            candidates = [
                lo,
                _clamp(baseline_val - 3 * std, lo, hi),
                _clamp(baseline_val - std,      lo, hi),
                baseline_val,
                _clamp(baseline_val + std,      lo, hi),
                _clamp(baseline_val + 3 * std,  lo, hi),
                hi,
            ]
            # Enforce integer constraint
            if param in INTEGER_PARAMS:
                candidates = [max(1, round(v)) for v in candidates]
            # Deduplicate while preserving order
            seen = set()
            unique = []
            for v in candidates:
                key = round(v, 6)
                if key not in seen:
                    seen.add(key)
                    unique.append(v)
            param_grids[param] = unique[:n_values]

        # Step 2: enumerate all combinations
        all_results: List[Dict[str, Any]] = []
        param_names = list(param_grids.keys())
        value_lists = [param_grids[p] for p in param_names]

        total_combos = 1
        for vl in value_lists:
            total_combos *= len(vl)
        logger.info(f"[GridSearch] Evaluating {total_combos} parameter combinations...")

        for combo in itertools.product(*value_lists):
            test_params = {**baseline_params, **dict(zip(param_names, combo))}
            sharpe = self._eval_params(test_params, data, symbol, days)
            stats  = self._backtest_params(test_params, data, symbol, days)

            win_rate = stats.get("win_rate", 0.0) / 100.0
            max_dd   = stats.get("max_dd",   0.0) / 100.0

            run_result = {
                "params":   test_params,
                "sharpe":   sharpe,
                "win_rate": win_rate,
                "max_dd":   max_dd,
            }
            all_results.append(run_result)

            # Log to registry
            self.registry.register_run(
                self.strategy_name,
                params=test_params,
                result={"sharpe": sharpe, "win_rate": win_rate, "max_dd": max_dd},
            )

        # Sort by Sharpe descending
        all_results.sort(key=lambda r: r["sharpe"], reverse=True)
        best = all_results[0] if all_results else {"params": baseline_params, "sharpe": 0.0}

        logger.info(
            f"[GridSearch] Best: sharpe={best['sharpe']:.4f} "
            f"params={best['params']}"
        )

        return {
            "best_params":        best["params"],
            "best_sharpe":        best["sharpe"],
            "top_10_results":     all_results[:10],
            "total_combinations": total_combos,
            "top_params_used":    top_params,
        }

    # ------------------------------------------------------------------
    # 3. Optuna Bayesian Search
    # ------------------------------------------------------------------

    def optuna_search(
        self,
        symbol: str,
        days: int,
        n_trials: int = 50,
        top_n_from_grid: int = 10,
        grid_result: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Bayesian optimisation using Optuna (TPE sampler).
        Seeds trials with top results from grid search, then explores further.
        Constraints: win_rate > 0.45, max_dd < 0.15.
        Returns {best_params_optuna, all_trials_list}.
        """
        try:
            import optuna
            optuna.logging.set_verbosity(optuna.logging.WARNING)
        except ImportError as e:
            raise ImportError("Optuna required: pip install optuna") from e

        n_trials = int(self.config.get("optimization.optuna_trials", n_trials))

        # Load (or run) grid search for warm-starting
        if grid_result is None:
            logger.info("[Optuna] Running grid search for warm-start data...")
            grid_result = self.grid_search(symbol, days)

        top_grid = grid_result.get("top_10_results", [])[:top_n_from_grid]
        baseline_params = dict(self.strategy.config)
        data = self._load_data(symbol, days)
        if data is None:
            return {"error": "No data", "best_params_optuna": baseline_params, "all_trials_list": []}

        all_trials_list: List[Dict[str, Any]] = []

        def objective(trial: "optuna.Trial") -> float:
            # Build test params from Optuna suggestions
            test_params = dict(baseline_params)
            for param, (lo, hi) in PARAM_BOUNDS.items():
                if param not in baseline_params:
                    continue
                if param in INTEGER_PARAMS:
                    test_params[param] = trial.suggest_int(param, int(lo), int(hi))
                else:
                    test_params[param] = trial.suggest_float(param, lo, hi)

            stats  = self._backtest_params(test_params, data, symbol, days)
            sharpe = _quick_sharpe(stats)

            win_rate = stats.get("win_rate", 0.0) / 100.0
            max_dd   = stats.get("max_dd",   0.0) / 100.0

            # Store extra info in trial user attrs
            trial.set_user_attr("win_rate", win_rate)
            trial.set_user_attr("max_dd",   max_dd)
            trial.set_user_attr("params",   test_params)

            # Penalise constraint violations
            min_wr  = float(self.config.get("optimization.min_win_rate",      0.45))
            max_dd_limit = float(self.config.get("optimization.max_drawdown_limit", 0.15))
            if win_rate < min_wr or max_dd > max_dd_limit:
                return -99.0

            # Log to registry
            self.registry.register_run(
                self.strategy_name,
                params=test_params,
                result={"sharpe": sharpe, "win_rate": win_rate, "max_dd": max_dd},
            )

            all_trials_list.append({
                "trial_number": trial.number,
                "sharpe":       sharpe,
                "win_rate":     win_rate,
                "max_dd":       max_dd,
                "params":       test_params,
            })
            return sharpe

        # Warm-start with grid search results
        sampler = optuna.samplers.TPESampler(seed=42)
        study   = optuna.create_study(direction="maximize", sampler=sampler)

        for grid_row in top_grid:
            p = grid_row.get("params", {})
            enqueue_dict = {}
            for param, (lo, hi) in PARAM_BOUNDS.items():
                if param not in p:
                    continue
                if param in INTEGER_PARAMS:
                    enqueue_dict[param] = max(int(lo), min(int(hi), int(p[param])))
                else:
                    enqueue_dict[param] = _clamp(float(p[param]), lo, hi)
            if enqueue_dict:
                study.enqueue_trial(enqueue_dict)

        study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

        best_trial  = study.best_trial
        best_params = best_trial.user_attrs.get("params", baseline_params)

        # Sort all trials by Sharpe
        all_trials_list.sort(key=lambda t: t["sharpe"], reverse=True)

        logger.info(
            f"[Optuna] Best: sharpe={best_trial.value:.4f} "
            f"params={best_params}"
        )

        return {
            "best_params_optuna": best_params,
            "best_sharpe":        best_trial.value,
            "top_5_results":      all_trials_list[:5],
            "all_trials_list":    all_trials_list,
            "n_trials_completed": len(study.trials),
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_data(self, symbol: str, days: int) -> Optional[pd.DataFrame]:
        """Delegate data loading to the WalkForwardValidator helper."""
        validator = WalkForwardValidator(self.strategy, self.config)
        data = validator._load_or_synthesise(symbol, days * 24)
        return data

    def _backtest_params(
        self,
        params: Dict[str, Any],
        data: pd.DataFrame,
        symbol: str,
        days: int,
    ) -> Dict[str, Any]:
        """Run BacktestEngineV2 on pre-loaded data with the given params."""
        strat  = _make_strategy(self.strategy, params)
        engine = BacktestEngineV2(strat, self.config)
        return engine.backtest_from_data(data, symbol, days)

    def _eval_params(
        self,
        params: Dict[str, Any],
        data: pd.DataFrame,
        symbol: str,
        days: int,
    ) -> float:
        """Run backtest and return Sharpe proxy."""
        stats = self._backtest_params(params, data, symbol, days)
        return _quick_sharpe(stats)
