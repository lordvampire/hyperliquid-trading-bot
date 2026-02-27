"""
PositionSizer — Dynamic position sizing driven by ConfigManager.

Formula:
    size_usd = account_balance
               * base_size_pct
               * (1 + volatility_scale * volatility)
               * signal_strength

Then clipped by max_position_pct and leverage_cap.

Usage:
    from config.manager import ConfigManager
    from position_sizing import PositionSizer

    config = ConfigManager("config/base.yaml", "backtest")
    sizer  = PositionSizer(config.get("position_sizing"))
    size   = sizer.calculate_size(10_000, volatility=0.03, signal_strength=0.8)
    contracts = sizer.calculate_contracts(size, entry_price=45_000)
"""

from __future__ import annotations
from typing import Dict, Any


class PositionSizer:
    """Compute USD-denominated position size with dynamic volatility scaling."""

    # Required config keys
    REQUIRED_KEYS = ("max_position_pct", "base_size_pct", "volatility_scale", "leverage_cap")

    def __init__(self, config: Dict[str, Any]):
        """
        Args:
            config: dict from ConfigManager.get("position_sizing").
                    Must contain: max_position_pct, base_size_pct,
                                  volatility_scale, leverage_cap.
        """
        missing = [k for k in self.REQUIRED_KEYS if k not in config]
        if missing:
            raise ValueError(
                f"[PositionSizer] Missing config keys: {missing}\n"
                f"  Tip: check config/base.yaml → position_sizing section."
            )
        self.max_position_pct: float = float(config["max_position_pct"])
        self.base_size_pct:    float = float(config["base_size_pct"])
        self.volatility_scale: float = float(config["volatility_scale"])
        self.leverage_cap:     float = float(config["leverage_cap"])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_size(
        self,
        account_balance: float,
        volatility: float,
        signal_strength: float,
    ) -> float:
        """
        Compute USD position size.

        Args:
            account_balance: Total account equity in USD.
            volatility:      Normalised volatility (e.g. daily ATR / price).
                             Typical range 0.01–0.10.
            signal_strength: Confidence score from strategy [0, 1].

        Returns:
            Position size in USD, capped at max_position_pct of balance.
        """
        signal_strength = max(0.0, min(1.0, signal_strength))
        volatility = max(0.0, volatility)

        raw_size = (
            account_balance
            * self.base_size_pct
            * (1.0 + self.volatility_scale * volatility)
            * signal_strength
        )

        max_allowed = account_balance * self.max_position_pct
        return round(min(raw_size, max_allowed), 4)

    def calculate_contracts(self, position_size_usd: float, entry_price: float) -> float:
        """
        Convert USD position size into number of contracts/coins.

        Args:
            position_size_usd: Size in USD (from calculate_size).
            entry_price:       Instrument price in USD.

        Returns:
            Number of contracts (fractional allowed).
        """
        if entry_price <= 0:
            raise ValueError(f"entry_price must be > 0, got {entry_price}")
        return round(position_size_usd / entry_price, 8)

    def apply_risk_limit(self, size: float, max_pct: float, account_balance: float) -> float:
        """
        Hard-cap position size to *max_pct* of account_balance.

        Args:
            size:            Proposed position size in USD.
            max_pct:         Maximum fraction of balance (e.g. 0.15 for 15%).
            account_balance: Current account equity in USD.

        Returns:
            Clipped position size in USD.
        """
        ceiling = account_balance * max_pct
        return round(min(size, ceiling), 4)
