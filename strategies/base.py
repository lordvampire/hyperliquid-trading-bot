"""Base strategy abstractions for the trading bot."""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import pandas as pd


@dataclass
class Signal:
    """Unified signal object returned by all strategies."""
    symbol: str
    direction: str          # "LONG", "SHORT", or "HOLD"
    strength: float         # 0.0 – 1.0  (composite confidence)
    stop_loss: float        # absolute price level (0.0 = not set)
    take_profit: float      # absolute price level (0.0 = not set)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if self.direction not in ("LONG", "SHORT", "HOLD"):
            raise ValueError(f"Signal direction must be LONG/SHORT/HOLD, got '{self.direction}'")
        if not (0.0 <= self.strength <= 1.0):
            raise ValueError(f"Signal strength must be in [0, 1], got {self.strength}")


class StrategyBase(ABC):
    """Abstract base class every strategy must implement."""

    def __init__(self, config: Dict[str, Any], mode: str = "backtest"):
        self.config = config
        self.mode = mode
        self._validate_config()

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def required_params(self) -> List[str]:
        """Return list of required config keys (validated on init)."""

    @abstractmethod
    def get_params(self) -> Dict[str, Any]:
        """Return the current effective config as a plain dict."""

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> List[Signal]:
        """
        Generate signals from OHLCV DataFrame.

        Args:
            data: DataFrame with columns [open, high, low, close, volume]

        Returns:
            List of Signal objects (one per bar or fewer — strategy decides).
        """

    # ------------------------------------------------------------------
    # Validation helper
    # ------------------------------------------------------------------

    def _validate_config(self) -> None:
        """Validate that all required params are present in self.config."""
        missing = [k for k in self.required_params() if k not in self.config]
        if missing:
            raise ValueError(
                f"[{self.__class__.__name__}] Missing required config keys: {missing}\n"
                f"  Provided keys: {list(self.config.keys())}\n"
                f"  Tip: check config/base.yaml → strategies section."
            )
