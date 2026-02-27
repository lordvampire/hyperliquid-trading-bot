"""
OptimizationRunner — Orchestrates the full optimization pipeline.

Stages:
    1. Sensitivity analysis  →  top 3 impactful params
    2. Grid search           →  343 combinations (7^3)
    3. Optuna search         →  Bayesian refinement (50 trials)
    4. Walk-forward validate →  overfitting check (3 windows)

Results are written to *output_dir* as JSON / CSV files.

Usage:
    from optimization_runner import OptimizationRunner

    runner  = OptimizationRunner("BTC", days=90)
    results = runner.quick_optimization("optimization_results")
    print(f"Best Sharpe: {results['sharpe_final']:.2f}")
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from config.manager import ConfigManager
from strategies.strategy_b import StrategyB
from param_registry import ParameterRegistry
from param_optimizer import ParamOptimizer
from backtest_validator import WalkForwardValidator

logger = logging.getLogger(__name__)


class OptimizationRunner:
    """Orchestrate all four optimization stages for a given symbol."""

    # Hardcoded top-3 for quick_optimization (skip sensitivity)
    QUICK_TOP_PARAMS = ["fast_period", "entry_threshold", "rsi_period"]

    def __init__(
        self,
        symbol: str,
        days: int,
        config_path: str = "config/base.yaml",
        mode: str = "backtest",
        registry_path: str = "param_history.json",
    ):
        self.symbol   = symbol
        self.days     = days
        self.config   = ConfigManager(config_path, mode)
        self.strategy = StrategyB(self.config.strategy("strategy_b"), mode)
        self.registry = ParameterRegistry(registry_path)
        self.optimizer = ParamOptimizer(
            self.strategy, self.config, self.registry, "strategy_b"
        )

    # ------------------------------------------------------------------
    # Full pipeline (~75 min in production)
    # ------------------------------------------------------------------

    def run_full_pipeline(self, output_dir: str = "optimization_results") -> Dict[str, Any]:
        """
        Stage 1: sensitivity_analysis
        Stage 2: grid_search on top 3
        Stage 3: optuna_search (50 trials)
        Stage 4: walk-forward validate best params
        Saves all artefacts to *output_dir*.
        Returns {best_params, sharpe_final, dd_final, win_rate_final}.
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        # ── Stage 1: Sensitivity ────────────────────────────────────────
        logger.info("[Pipeline] Stage 1: Sensitivity analysis...")
        sensitivity = self.optimizer.sensitivity_analysis(self.symbol, self.days)
        self._save_json(sensitivity, output_dir, "sensitivity_report.json")
        logger.info(f"[Pipeline] Sensitivity done in {time.time()-t0:.0f}s")

        # ── Stage 2: Grid search ────────────────────────────────────────
        t1 = time.time()
        logger.info("[Pipeline] Stage 2: Grid search (top 3 params)...")
        grid = self.optimizer.grid_search(self.symbol, self.days, top_n_params=3)
        self._save_grid_csv(grid.get("top_10_results", []), output_dir, "grid_search_results.csv")
        logger.info(f"[Pipeline] Grid search done in {time.time()-t1:.0f}s — best Sharpe: {grid.get('best_sharpe', 0):.4f}")

        # ── Stage 3: Optuna ─────────────────────────────────────────────
        t2 = time.time()
        logger.info("[Pipeline] Stage 3: Optuna Bayesian search (50 trials)...")
        n_trials = int(self.config.get("optimization.optuna_trials", 50))
        optuna_result = self.optimizer.optuna_search(
            self.symbol, self.days,
            n_trials=n_trials,
            grid_result=grid,
        )
        self._save_json(
            {k: v for k, v in optuna_result.items() if k != "all_trials_list"},
            output_dir, "optuna_trials.json",
        )
        logger.info(f"[Pipeline] Optuna done in {time.time()-t2:.0f}s — best Sharpe: {optuna_result.get('best_sharpe', 0):.4f}")

        best_params = optuna_result.get("best_params_optuna") or grid.get("best_params", {})

        # ── Stage 4: Walk-forward validate ──────────────────────────────
        logger.info("[Pipeline] Stage 4: Walk-forward validation...")
        valid = self.validate_params(best_params)
        wf_summary = self._walk_forward_summary(best_params)
        self._save_json(wf_summary, output_dir, "walk_forward_validation.json")

        # Final metrics from the last backtest stats
        final_stats = self._final_stats(best_params)
        result = {
            "best_params":     best_params,
            "sharpe_final":    final_stats["sharpe"],
            "dd_final":        final_stats["max_dd"] / 100.0,
            "win_rate_final":  final_stats["win_rate"] / 100.0,
            "valid":           valid,
            "total_seconds":   round(time.time() - t0, 1),
        }
        self._save_json(result, output_dir, "final_best_params.json")

        logger.info(
            f"[Pipeline] Complete in {result['total_seconds']:.0f}s — "
            f"Sharpe={result['sharpe_final']:.4f} WR={result['win_rate_final']:.1%} "
            f"MaxDD={result['dd_final']:.2%}"
        )
        return result

    # ------------------------------------------------------------------
    # Quick optimization (~20-30 min — for testing)
    # ------------------------------------------------------------------

    def quick_optimization(self, output_dir: str = "optimization_results") -> Dict[str, Any]:
        """
        Skip sensitivity (use hardcoded top-3).
        Grid search only (no Optuna).
        Returns {best_params, sharpe_final, dd_final, win_rate_final}.
        """
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        t0 = time.time()

        logger.info("[QuickOpt] Grid search only (hardcoded top-3 params)...")
        grid = self.optimizer.grid_search(
            self.symbol, self.days, top_n_params=3
        )
        self._save_grid_csv(grid.get("top_10_results", []), output_dir, "grid_search_results.csv")

        best_params = grid.get("best_params", dict(self.strategy.config))
        final_stats = self._final_stats(best_params)
        result = {
            "best_params":     best_params,
            "sharpe_final":    final_stats["sharpe"],
            "dd_final":        final_stats["max_dd"] / 100.0,
            "win_rate_final":  final_stats["win_rate"] / 100.0,
            "total_seconds":   round(time.time() - t0, 1),
        }
        self._save_json(result, output_dir, "final_best_params.json")

        logger.info(
            f"[QuickOpt] Done in {result['total_seconds']:.0f}s — "
            f"Sharpe={result['sharpe_final']:.4f}"
        )
        return result

    # ------------------------------------------------------------------
    # Param validation
    # ------------------------------------------------------------------

    def validate_params(self, best_params: Dict[str, Any]) -> bool:
        """
        Walk-forward validate *best_params*.
        Pass criteria:
            • Sharpe std < consistency_threshold (default 0.3)
            • test_sharpe > 0.5 * train_sharpe  (no overfitting)
        Returns True if passes.
        """
        from strategies.strategy_b import StrategyB as SB

        threshold = float(self.config.get("optimization.consistency_threshold", 0.3))
        n_windows = int(self.config.get("optimization.walk_forward_windows", 3))

        strat  = SB(best_params, self.strategy.mode)
        wfv    = WalkForwardValidator(strat, self.config)
        result = wfv.run_walk_forward(self.symbol, self.days)

        if "error" in result:
            logger.warning(f"[Validate] Walk-forward error: {result['error']}")
            return False

        std_sharpe = result.get("std_sharpe", 999.0)
        overfit    = result.get("overfitting_detected", True)

        passed = (std_sharpe < threshold) and (not overfit)
        logger.info(
            f"[Validate] std_sharpe={std_sharpe:.4f} overfit={overfit} → {'PASS' if passed else 'FAIL'}"
        )
        return passed

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _final_stats(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run one full backtest with *params* and return stats."""
        from strategies.strategy_b import StrategyB as SB
        from backtest_engine_v2 import BacktestEngineV2

        strat  = SB(params, self.strategy.mode)
        engine = BacktestEngineV2(strat, self.config)
        data   = self.optimizer._load_data(self.symbol, self.days)
        if data is None:
            return {"sharpe": 0.0, "max_dd": 0.0, "win_rate": 0.0}

        stats  = engine.backtest_from_data(data, self.symbol, self.days)
        ret    = stats.get("return_pct", 0.0)
        dd     = stats.get("max_dd", 1.0) or 1.0
        stats["sharpe"] = round(ret / dd, 4)
        return stats

    def _walk_forward_summary(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """Run walk-forward and return the summary dict."""
        from strategies.strategy_b import StrategyB as SB

        strat  = SB(params, self.strategy.mode)
        wfv    = WalkForwardValidator(strat, self.config)
        return wfv.run_walk_forward(self.symbol, self.days)

    @staticmethod
    def _save_json(data: Any, output_dir: str, filename: str) -> None:
        path = Path(output_dir) / filename
        with path.open("w") as fh:
            json.dump(data, fh, indent=2, default=str)
        logger.info(f"[Runner] Saved {path}")

    @staticmethod
    def _save_grid_csv(results: List[Dict[str, Any]], output_dir: str, filename: str) -> None:
        if not results:
            return
        path = Path(output_dir) / filename
        # Flatten params into columns
        fieldnames = ["sharpe", "win_rate", "max_dd"]
        param_keys = list(results[0].get("params", {}).keys())
        all_fields = fieldnames + [f"param_{k}" for k in param_keys]

        with path.open("w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            for row in results:
                flat = {
                    "sharpe":   row.get("sharpe", ""),
                    "win_rate": row.get("win_rate", ""),
                    "max_dd":   row.get("max_dd", ""),
                }
                for k in param_keys:
                    flat[f"param_{k}"] = row.get("params", {}).get(k, "")
                writer.writerow(flat)
        logger.info(f"[Runner] Saved {path}")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

    parser = argparse.ArgumentParser(description="Run parameter optimization")
    parser.add_argument("--symbol", default="BTC", help="Trading symbol (default: BTC)")
    parser.add_argument("--days",   type=int, default=90, help="History in days (default: 90)")
    parser.add_argument("--output", default="optimization_results", help="Output directory")
    parser.add_argument("--quick",  action="store_true", help="Quick grid-only optimization")
    args = parser.parse_args()

    runner = OptimizationRunner(args.symbol, days=args.days)

    if args.quick:
        results = runner.quick_optimization(args.output)
    else:
        results = runner.run_full_pipeline(args.output)

    print("\n=== OPTIMIZATION COMPLETE ===")
    print(f"Best Sharpe:  {results['sharpe_final']:.2f}")
    print(f"Best Params:  {results['best_params']}")
    print(f"Win Rate:     {results['win_rate_final']:.1%}")
    print(f"Max DD:       {results['dd_final']:.2%}")
    print(f"Time:         {results.get('total_seconds', 0):.0f}s")
    sys.exit(0)
