"""
ParameterRegistry — Human-readable experiment tracker for strategy tuning.

Stores param sets + backtest results in a JSON file.
Supports best-param lookup, run history, and CSV export.

Usage:
    from param_registry import ParameterRegistry

    registry = ParameterRegistry("param_history.json")
    run_id = registry.register_run(
        "strategy_b",
        params={"fast_period": 5, "slow_period": 20},
        result={"sharpe": 1.4, "max_dd": 8.2, "win_rate": 0.55},
    )
    best = registry.get_best_params("strategy_b", metric="sharpe")
    print(f"Best params: {best}")
"""

from __future__ import annotations
import csv
import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


class ParameterRegistry:
    """
    Persist strategy parameter experiments and retrieve top performers.

    Args:
        db_path: Path to the JSON file used as the backing store.
                 Created automatically if it does not exist.
    """

    def __init__(self, db_path: str = "param_history.json"):
        self.db_path = Path(db_path)
        self._data: Dict[str, List[Dict]] = self._load()

    # ------------------------------------------------------------------
    # Write API
    # ------------------------------------------------------------------

    def register_run(
        self,
        strategy_name: str,
        params: Dict[str, Any],
        result: Dict[str, Any],
    ) -> str:
        """
        Record a single parameter experiment.

        Args:
            strategy_name: Logical name, e.g. "strategy_b".
            params:        The param dict used in this run.
            result:        Backtest output — must contain at least
                           "sharpe", "max_dd", "win_rate".

        Returns:
            Unique run_id string (timestamp + uuid suffix).
        """
        ts     = time.time()
        run_id = f"{int(ts)}-{uuid.uuid4().hex[:8]}"

        entry = {
            "run_id":    run_id,
            "timestamp": datetime.fromtimestamp(ts, tz=timezone.utc).isoformat(),
            "params":    dict(params),
            "sharpe":    float(result.get("sharpe",   0.0)),
            "max_dd":    float(result.get("max_dd",   0.0)),
            "win_rate":  float(result.get("win_rate", 0.0)),
            "extra":     {k: v for k, v in result.items()
                          if k not in ("sharpe", "max_dd", "win_rate")},
        }

        self._data.setdefault(strategy_name, []).append(entry)
        self._save()
        return run_id

    # ------------------------------------------------------------------
    # Read API
    # ------------------------------------------------------------------

    def get_best_params(
        self,
        strategy_name: str,
        metric: str = "sharpe",
    ) -> Optional[Dict[str, Any]]:
        """
        Return the param dict of the run with the highest *metric* value.

        Args:
            strategy_name: Strategy key (same as used in register_run).
            metric:        One of "sharpe", "win_rate" (higher = better)
                           or "max_dd" (lower = better).

        Returns:
            Params dict of the best run, or None if no runs exist.
        """
        runs = self._data.get(strategy_name, [])
        if not runs:
            return None

        reverse = metric != "max_dd"    # max_dd: lower is better
        best = sorted(runs, key=lambda r: r.get(metric, 0.0), reverse=reverse)[0]
        return dict(best["params"])

    def get_run_history(
        self,
        strategy_name: str,
        limit: int = 10,
        sort_by: str = "sharpe",
    ) -> List[Dict[str, Any]]:
        """
        Return the last *limit* runs sorted by *sort_by* (descending).

        Args:
            strategy_name: Strategy key.
            limit:         Maximum number of records to return.
            sort_by:       Metric to sort by.

        Returns:
            List of run dicts (newest first, then sorted by metric).
        """
        runs = self._data.get(strategy_name, [])
        reverse = sort_by != "max_dd"
        sorted_runs = sorted(runs, key=lambda r: r.get(sort_by, 0.0), reverse=reverse)
        return sorted_runs[:limit]

    def export_csv(self, filepath: str, strategy_name: str) -> None:
        """
        Export all runs for *strategy_name* to a CSV file.

        Args:
            filepath:      Destination file path.
            strategy_name: Strategy key.
        """
        runs = self._data.get(strategy_name, [])
        if not runs:
            return

        fieldnames = ["run_id", "timestamp", "sharpe", "max_dd", "win_rate"]
        # Collect all param keys
        param_keys: List[str] = []
        for r in runs:
            for k in r.get("params", {}):
                if k not in param_keys:
                    param_keys.append(k)

        all_fields = fieldnames + [f"param_{k}" for k in param_keys]

        with open(filepath, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=all_fields, extrasaction="ignore")
            writer.writeheader()
            for r in runs:
                row = {
                    "run_id":    r["run_id"],
                    "timestamp": r["timestamp"],
                    "sharpe":    r["sharpe"],
                    "max_dd":    r["max_dd"],
                    "win_rate":  r["win_rate"],
                }
                for k in param_keys:
                    row[f"param_{k}"] = r["params"].get(k, "")
                writer.writerow(row)

    def clear(self, strategy_name: Optional[str] = None) -> None:
        """Remove all runs (optionally for a single strategy only)."""
        if strategy_name:
            self._data.pop(strategy_name, None)
        else:
            self._data = {}
        self._save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> Dict[str, List[Dict]]:
        if self.db_path.exists():
            try:
                with self.db_path.open("r") as fh:
                    return json.load(fh)
            except json.JSONDecodeError:
                return {}
        return {}

    def _save(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self.db_path.open("w") as fh:
            json.dump(self._data, fh, indent=2)
