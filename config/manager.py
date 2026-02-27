"""ConfigManager — loads YAML config with env-var overrides and mode layering."""

from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except ImportError as exc:
    raise ImportError("PyYAML is required: pip install pyyaml") from exc


class ConfigManager:
    """
    Loads a base YAML config file and optionally merges a mode-specific file.

    Load order (later overrides earlier):
        1. base YAML  (e.g. config/base.yaml)
        2. mode YAML  (e.g. config/backtest.yaml) — if it exists
        3. Environment variables: TRADING_KEY=value  →  {"key": "value"}

    Nested key access via dot notation:
        config.get("backtest.slippage_pct", default=0.0)

    Usage:
        config = ConfigManager("config/base.yaml", "backtest")
        config.get("backtest.slippage_pct")    # 0.08
        config.strategy("strategy_b")          # dict of strategy params
    """

    def __init__(self, path: str, mode: str = "backtest"):
        self.mode = mode
        self._data: Dict[str, Any] = {}

        base_path = Path(path)
        if not base_path.exists():
            raise FileNotFoundError(f"Config file not found: {base_path.resolve()}")

        # 1. Load base YAML
        self._data = self._load_yaml(base_path)

        # 2. Merge mode-specific YAML (config/<mode>.yaml) if present
        mode_path = base_path.parent / f"{mode}.yaml"
        if mode_path.exists():
            mode_data = self._load_yaml(mode_path)
            self._deep_merge(self._data, mode_data)

        # 3. Apply env-var overrides: TRADING_KEY=value → _data["key"] = value
        self._apply_env_overrides()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value by dot-notation key.
        Example: get("backtest.slippage_pct") → 0.08
        """
        parts = key.split(".")
        node = self._data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def strategy(self, name: str) -> Dict[str, Any]:
        """
        Return the config dict for a named strategy.
        Example: config.strategy("strategy_b") → {"fast_period": 5, ...}
        """
        strat = self.get(f"strategies.{name}")
        if strat is None:
            raise KeyError(
                f"Strategy '{name}' not found in config.\n"
                f"  Available strategies: {list(self.get('strategies', {}).keys())}"
            )
        return dict(strat)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _load_yaml(path: Path) -> Dict[str, Any]:
        with path.open("r") as fh:
            data = yaml.safe_load(fh)
        return data or {}

    @staticmethod
    def _deep_merge(base: dict, override: dict) -> None:
        """Merge override into base in-place (nested dicts are merged, not replaced)."""
        for key, value in override.items():
            if key in base and isinstance(base[key], dict) and isinstance(value, dict):
                ConfigManager._deep_merge(base[key], value)
            else:
                base[key] = value

    def _apply_env_overrides(self) -> None:
        """
        Read env vars prefixed with TRADING_ and inject into config.
        TRADING_KEY=value  →  _data["key"] = parsed(value)
        TRADING_SECTION__KEY=value  →  _data["section"]["key"] = parsed(value)
        (double-underscore separates levels)
        """
        prefix = "TRADING_"
        for env_key, raw_value in os.environ.items():
            if not env_key.startswith(prefix):
                continue
            path_parts = env_key[len(prefix):].lower().split("__")
            node = self._data
            for part in path_parts[:-1]:
                node = node.setdefault(part, {})
            node[path_parts[-1]] = self._parse_value(raw_value)

    @staticmethod
    def _parse_value(raw: str) -> Any:
        """Try to parse env-var value as Python literal, fall back to string."""
        try:
            return int(raw)
        except ValueError:
            pass
        try:
            return float(raw)
        except ValueError:
            pass
        if raw.lower() in ("true", "false"):
            return raw.lower() == "true"
        return raw
