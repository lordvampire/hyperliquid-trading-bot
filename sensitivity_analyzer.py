"""
SensitivityAnalyzer — Detailed single-parameter analysis and correlation matrices.

Wraps ParamOptimizer to provide finer-grained sensitivity insights:
  • analyze_single_param: plots Sharpe vs. param value (saves PNG)
  • correlation_matrix:   correlation between param changes and Sharpe

Usage:
    from param_optimizer import ParamOptimizer
    from sensitivity_analyzer import SensitivityAnalyzer

    analyzer = SensitivityAnalyzer(optimizer)
    result   = analyzer.analyze_single_param("BTC", "fast_period", days=30)
    matrix   = analyzer.correlation_matrix("BTC", days=30)
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

from param_optimizer import ParamOptimizer, PARAM_BOUNDS, INTEGER_PARAMS, _clamp

logger = logging.getLogger(__name__)


class SensitivityAnalyzer:
    """Detailed parameter sensitivity analysis with chart output."""

    VARIATIONS = [0.7, 0.8, 0.9, 1.0, 1.1, 1.2, 1.3]   # ±30 % steps

    def __init__(self, optimizer: ParamOptimizer):
        self.optimizer = optimizer

    # ------------------------------------------------------------------
    # 1. Single-param sensitivity
    # ------------------------------------------------------------------

    def analyze_single_param(
        self,
        symbol: str,
        param_name: str,
        days: int,
        output_dir: str = "optimization_results",
    ) -> Dict[str, Any]:
        """
        Vary *param_name* across ±30 % of its baseline value, backtest each
        variation, and save a Sharpe-vs-param-value PNG chart.

        Returns:
            {param_name, baseline_value, sensitivities: [...], chart_path}
        """
        baseline_params = dict(self.optimizer.strategy.config)

        if param_name not in baseline_params:
            return {"error": f"Param '{param_name}' not in strategy config"}

        baseline_val = float(baseline_params[param_name])
        lo, hi = PARAM_BOUNDS.get(param_name, (baseline_val * 0.5, baseline_val * 2.0))

        data = self.optimizer._load_data(symbol, days)
        if data is None:
            return {"error": f"No data for {symbol}"}

        # Use short window (1 day of hourly bars) for speed
        quick_days = max(2, days // 15)
        quick_data = data.tail(quick_days * 24).reset_index(drop=True)

        sensitivities: List[Dict[str, Any]] = []
        param_values: List[float] = []
        sharpe_values: List[float] = []

        for factor in self.VARIATIONS:
            new_val = _clamp(baseline_val * factor, lo, hi)
            if param_name in INTEGER_PARAMS:
                new_val = max(1, round(new_val))

            test_params = {**baseline_params, param_name: new_val}
            stats  = self.optimizer._backtest_params(test_params, quick_data, symbol, quick_days)
            sharpe = self.optimizer._eval_params(test_params, quick_data, symbol, quick_days)
            win_rate = stats.get("win_rate", 0.0)

            sensitivities.append({
                "factor":     factor,
                "param_value": new_val,
                "sharpe":     round(sharpe, 4),
                "win_rate":   round(win_rate, 2),
            })
            param_values.append(new_val)
            sharpe_values.append(sharpe)

            logger.info(
                f"[SensitivityAnalyzer] {param_name}={new_val:.4g} "
                f"sharpe={sharpe:.4f}"
            )

        chart_path = self._save_chart(
            param_name=param_name,
            param_values=param_values,
            sharpe_values=sharpe_values,
            baseline_val=baseline_val,
            output_dir=output_dir,
        )

        return {
            "param_name":     param_name,
            "baseline_value": baseline_val,
            "sensitivities":  sensitivities,
            "chart_path":     chart_path,
        }

    # ------------------------------------------------------------------
    # 2. Correlation matrix
    # ------------------------------------------------------------------

    def correlation_matrix(self, symbol: str, days: int) -> np.ndarray:
        """
        Compute the correlation matrix between per-param changes and Sharpe changes.

        Runs the sensitivity_analysis from ParamOptimizer with tracking vectors,
        then calculates pairwise param–Sharpe correlations.

        Returns:
            np.ndarray of shape (n_params, n_params) — correlation matrix.
            Rows/cols correspond to sorted param names (see .param_names property).
        """
        params   = list(self.optimizer.strategy.config.keys())
        # Only include known-bounded params
        params   = [p for p in params if p in PARAM_BOUNDS]
        self._param_names = params

        data = self.optimizer._load_data(symbol, days)
        if data is None:
            n = len(params)
            return np.eye(n)

        baseline_p = dict(self.optimizer.strategy.config)
        baseline_s = self.optimizer._eval_params(baseline_p, data, symbol, days)

        # For each param, collect (delta_param_pct, delta_sharpe) across variations
        # Shape: (n_params, n_variations)
        delta_sharpe_matrix: List[List[float]] = []

        for param in params:
            baseline_val = float(baseline_p.get(param, 1.0))
            lo, hi = PARAM_BOUNDS.get(param, (baseline_val * 0.5, baseline_val * 2.0))
            row: List[float] = []

            for factor in [0.7, 0.85, 1.0, 1.15, 1.3]:
                new_val = _clamp(baseline_val * factor, lo, hi)
                if param in INTEGER_PARAMS:
                    new_val = max(1, round(new_val))

                test_params = {**baseline_p, param: new_val}
                s = self.optimizer._eval_params(test_params, data, symbol, days)
                row.append(s - baseline_s)

            delta_sharpe_matrix.append(row)

        arr = np.array(delta_sharpe_matrix, dtype=float)   # (n_params, n_variations)

        # Correlation matrix: each row is a time-series of sharpe deltas
        # If all variations are identical, replace row with zeros to avoid NaN
        with np.errstate(divide="ignore", invalid="ignore"):
            corr = np.corrcoef(arr)   # (n_params, n_params)

        corr = np.nan_to_num(corr, nan=0.0)
        return corr

    @property
    def param_names(self) -> List[str]:
        """Param names used in the last correlation_matrix call."""
        return getattr(self, "_param_names", list(PARAM_BOUNDS.keys()))

    # ------------------------------------------------------------------
    # Chart helper
    # ------------------------------------------------------------------

    def _save_chart(
        self,
        param_name: str,
        param_values: List[float],
        sharpe_values: List[float],
        baseline_val: float,
        output_dir: str,
    ) -> str:
        """Save a Sharpe-vs-param-value chart to *output_dir*. Returns file path."""
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        chart_path = str(Path(output_dir) / f"sensitivity_{param_name}.png")

        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt

            fig, ax = plt.subplots(figsize=(8, 4))
            ax.plot(param_values, sharpe_values, "o-", color="steelblue", linewidth=2)
            ax.axvline(baseline_val, color="red", linestyle="--", alpha=0.6, label="Baseline")
            ax.set_xlabel(param_name, fontsize=12)
            ax.set_ylabel("Sharpe (proxy)", fontsize=12)
            ax.set_title(f"Sensitivity: {param_name} vs Sharpe", fontsize=14)
            ax.legend()
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            plt.savefig(chart_path, dpi=120)
            plt.close(fig)
            logger.info(f"[SensitivityAnalyzer] Chart saved: {chart_path}")
        except ImportError:
            # matplotlib not required — save a placeholder
            with open(chart_path.replace(".png", ".txt"), "w") as fh:
                fh.write(f"# Sensitivity chart for {param_name}\n")
                for pv, sv in zip(param_values, sharpe_values):
                    fh.write(f"{pv:.4g}\t{sv:.4f}\n")
            chart_path = chart_path.replace(".png", ".txt")
            logger.info(f"[SensitivityAnalyzer] matplotlib not available; saved TSV: {chart_path}")
        except Exception as exc:
            logger.warning(f"[SensitivityAnalyzer] Chart save failed: {exc}")

        return chart_path
