"""
LiveDeployment — Orchestrates live (mainnet) trading with full safety guardrails.

Flow per signal:
    1. Safety pre-trade check (check_pre_trade)
    2. Position sizing (PositionSizer)
    3. Order placement (HyperliquidExchange)
    4. Audit logging (SafetyManager.log_trade)
    5. Registry tracking (ParameterRegistry)

Usage:
    from live_deployment import LiveDeployment
    from safety_manager import SafetyManager
    from strategies.strategy_b import StrategyB
    from config.manager import ConfigManager

    config   = ConfigManager("config/base.yaml", "live")
    strategy = StrategyB(config.strategy("strategy_b"), "live")
    safety   = SafetyManager(config)
    exchange = get_exchange()           # from exchange.py

    deployer = LiveDeployment(strategy, config, exchange, safety)
    deployer.start_trading()

    result = deployer.process_signal(signal, current_price=45_000, balance=1000)
"""

from __future__ import annotations

import logging
import os
import shutil
import time
import uuid
from datetime import datetime, timezone, date
from pathlib import Path
from typing import Any, Dict, List, Optional

from strategies.base import StrategyBase, Signal
from config.manager import ConfigManager
from position_sizing import PositionSizer
from param_registry import ParameterRegistry
from safety_manager import SafetyManager

logger = logging.getLogger(__name__)


class LiveDeployment:
    """
    Orchestrate live trading with safety guards, audit trail, and daily management.

    Args:
        strategy:       Any StrategyBase instance.
        config:         ConfigManager (loaded with mode="live").
        exchange:       Hyperliquid Exchange client (or None for dry-run).
        safety_manager: SafetyManager instance.
    """

    def __init__(
        self,
        strategy: StrategyBase,
        config: ConfigManager,
        exchange: Any,          # hyperliquid.exchange.Exchange or None
        safety_manager: SafetyManager,
    ):
        self.strategy  = strategy
        self.config    = config
        self.exchange  = exchange
        self.safety    = safety_manager

        # Position sizer
        self.sizer = PositionSizer(config.get("position_sizing", {}))

        # Parameter registry for tracking
        registry_path = config.get("deployment.registry_path", "param_history.json")
        self.registry = ParameterRegistry(registry_path)

        # Runtime state
        self._running:         bool = False
        self._start_balance:   float = 0.0
        self._daily_pnl:       float = 0.0
        self._open_positions:  Dict[str, Dict[str, Any]] = {}   # symbol → position dict
        self._trade_history:   List[Dict[str, Any]] = []
        self._started_at:      Optional[datetime] = None

        # Log archiving
        self._log_dir = Path(config.get("safety.audit_log_path", "logs/audit.log")).parent

        logger.info("[LiveDeployment] Initialized — waiting for start_trading()")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start_trading(self) -> None:
        """
        Initialize all components and begin trading session.

        - Fetches current balance (or uses configured starting capital).
        - Resets daily counters.
        - Marks bot as running.
        """
        self._running = True
        self._started_at = datetime.now(timezone.utc)

        # Starting capital from config (fallback if exchange unavailable)
        capital = float(self.config.get("deployment.starting_capital", 1000.0))
        if self.exchange is not None:
            try:
                from config import cfg
                from exchange import fetch_balance
                bal_data = fetch_balance()
                account_value = bal_data.get("account_value", capital)
                capital = float(account_value)
            except Exception as exc:
                logger.warning(f"[LiveDeployment] Could not fetch live balance: {exc}. Using config value.")

        self._start_balance = capital
        self.daily_reset()      # Sets daily P&L baseline in SafetyManager

        logger.info(
            f"[LiveDeployment] ✅ Trading started at "
            f"{self._started_at.isoformat()} | balance={capital:.2f}"
        )
        self.safety.log_trade(
            trade_id="SESSION_START",
            symbol="SYSTEM",
            signal=Signal("SYSTEM", "HOLD", 0.0, 0.0, 0.0,
                          {"event": "session_start", "balance": capital}),
            entry_price=0.0,
            size=0.0,
            status="session_start",
        )

    # ------------------------------------------------------------------
    # Signal processing
    # ------------------------------------------------------------------

    def process_signal(
        self,
        signal: Signal,
        current_price: float,
        balance: float,
    ) -> Dict[str, Any]:
        """
        Process a trading signal end-to-end.

        1. Safety check
        2. Position sizing
        3. Order placement
        4. Audit + registry

        Returns:
            dict with status="executed" | "rejected" | "error"
        """
        if not self._running:
            return {"status": "error", "reason": "LiveDeployment not started — call start_trading()"}

        # --- Step 1: Safety check -----------------------------------------
        is_safe, reason = self.safety.check_pre_trade(signal, current_price, balance)
        if not is_safe:
            result = {"status": "rejected", "reason": reason, "symbol": signal.symbol}
            self.safety.log_trade(
                trade_id=f"REJECTED-{uuid.uuid4().hex[:8]}",
                symbol=signal.symbol,
                signal=signal,
                entry_price=current_price,
                size=0.0,
                status="rejected",
            )
            logger.info(f"[LiveDeployment] Signal rejected: {reason}")
            return result

        # --- Step 2: Position sizing ----------------------------------------
        volatility = float(signal.metadata.get("volatility", 0.03))
        size_usd   = self.sizer.calculate_size(balance, volatility, signal.strength)
        contracts  = self.sizer.calculate_contracts(size_usd, current_price)

        # --- Step 3: Place order --------------------------------------------
        trade_id = f"T-{int(time.time())}-{uuid.uuid4().hex[:6]}"
        order_id: Optional[str] = None

        if self.exchange is not None:
            try:
                is_buy = signal.direction == "LONG"
                resp = self.exchange.order(
                    signal.symbol,
                    is_buy,
                    contracts,
                    current_price,
                    {"limit": {"tif": "Ioc"}},
                )
                order_id = str(resp.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("resting", {}).get("oid", trade_id))
                logger.info(f"[LiveDeployment] Order placed: {order_id}")
            except Exception as exc:
                logger.error(f"[LiveDeployment] Order placement failed: {exc}")
                self.safety.log_trade(trade_id, signal.symbol, signal, current_price, contracts, "error")
                return {"status": "error", "reason": str(exc), "trade_id": trade_id}
        else:
            order_id = f"SIM-{trade_id}"
            logger.info(f"[LiveDeployment] Dry-run (no exchange) — simulated order: {order_id}")

        # --- Step 4: Record open position -----------------------------------
        position = {
            "trade_id":    trade_id,
            "order_id":    order_id,
            "symbol":      signal.symbol,
            "direction":   signal.direction,
            "entry_price": current_price,
            "size":        contracts,
            "size_usd":    size_usd,
            "stop_loss":   signal.stop_loss,
            "take_profit": signal.take_profit,
            "opened_at":   datetime.now(timezone.utc).isoformat(),
        }
        self._open_positions[signal.symbol] = position
        self._trade_history.append({"type": "open", **position})

        # Audit log
        self.safety.log_trade(trade_id, signal.symbol, signal, current_price, contracts, "executed")

        # Registry tracking
        self.registry.register_run(
            "live_trades",
            params={"symbol": signal.symbol, "direction": signal.direction, "order_id": order_id},
            result={"sharpe": 0.0, "max_dd": 0.0, "win_rate": 0.0, "size_usd": size_usd},
        )

        result = {
            "status":      "executed",
            "trade_id":    trade_id,
            "order_id":    order_id,
            "symbol":      signal.symbol,
            "direction":   signal.direction,
            "entry_price": current_price,
            "size":        contracts,
            "size_usd":    size_usd,
        }
        logger.info(f"[LiveDeployment] ✅ Trade executed: {result}")
        return result

    # ------------------------------------------------------------------
    # Position management
    # ------------------------------------------------------------------

    def close_position(
        self,
        symbol: str,
        reason: str,
        exit_price: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Market-close an open position and record the exit.

        Args:
            symbol:     Trading symbol (e.g. "BTC").
            reason:     Why the position is being closed.
            exit_price: Current price. If None, uses the entry_price (flat).

        Returns:
            dict with status, pnl, reason.
        """
        position = self._open_positions.get(symbol)
        if position is None:
            return {"status": "error", "reason": f"No open position for {symbol}"}

        entry_price = position["entry_price"]
        size        = position["size"]
        direction   = position["direction"]
        exit_px     = exit_price if exit_price is not None else entry_price

        # P&L calculation
        if direction == "LONG":
            pnl = (exit_px - entry_price) * size
        else:
            pnl = (entry_price - exit_px) * size

        # Update daily P&L
        self._daily_pnl += pnl
        self.safety.update_daily_pnl(pnl)

        # Place closing order
        close_order_id: Optional[str] = None
        if self.exchange is not None:
            try:
                is_buy = direction == "SHORT"   # close SHORT → buy
                resp = self.exchange.order(
                    symbol, is_buy, size, exit_px, {"limit": {"tif": "Ioc"}}
                )
                close_order_id = str(resp.get("response", {}).get("data", {}).get("statuses", [{}])[0].get("resting", {}).get("oid", "N/A"))
            except Exception as exc:
                logger.error(f"[LiveDeployment] Close order failed: {exc}")

        # Record
        close_entry = {
            "type":        "close",
            "symbol":      symbol,
            "direction":   direction,
            "entry_price": entry_price,
            "exit_price":  exit_px,
            "size":        size,
            "pnl":         pnl,
            "reason":      reason,
            "closed_at":   datetime.now(timezone.utc).isoformat(),
        }
        self._trade_history.append(close_entry)
        del self._open_positions[symbol]

        # Audit
        trade_id = position.get("trade_id", "UNKNOWN")
        self.safety.log_trade(
            f"{trade_id}-CLOSE",
            symbol,
            Signal(symbol, direction, 0.0, 0.0, 0.0, {"reason": reason}),
            exit_px,
            size,
            "closed",
            pnl=pnl,
        )

        logger.info(
            f"[LiveDeployment] Position closed: {symbol} pnl={pnl:+.4f} reason={reason}"
        )
        return {"status": "closed", "symbol": symbol, "pnl": pnl, "reason": reason,
                "close_order_id": close_order_id}

    # ------------------------------------------------------------------
    # Daily reset
    # ------------------------------------------------------------------

    def daily_reset(self) -> None:
        """
        Called at 00:00 UTC.
        - Resets daily P&L counter in SafetyManager.
        - Archives previous audit log.
        - Generates and logs daily report.
        """
        yesterday = (
            datetime.now(timezone.utc).strftime("%Y-%m-%d")
            if self._started_at else "bootstrap"
        )

        # Archive previous audit log
        audit_path = self.safety.audit_log_path
        if audit_path.exists() and audit_path.stat().st_size > 0:
            archive_path = audit_path.parent / f"audit_{yesterday}.log"
            try:
                shutil.copy2(str(audit_path), str(archive_path))
                logger.info(f"[LiveDeployment] Audit log archived → {archive_path}")
            except Exception as exc:
                logger.warning(f"[LiveDeployment] Archive failed: {exc}")

        # Generate daily report BEFORE resetting
        report = self.safety.generate_daily_report()
        report_path = self._log_dir / f"report_{yesterday}.html"
        try:
            report_path.write_text(report)
            logger.info(f"[LiveDeployment] Daily report saved → {report_path}")
        except Exception as exc:
            logger.warning(f"[LiveDeployment] Report save failed: {exc}")

        # Reset daily counters
        self.safety.set_daily_start_balance(self._start_balance)
        self._daily_pnl = 0.0

        logger.info(f"[LiveDeployment] Daily reset complete — new day starts fresh")

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    def get_status(self) -> Dict[str, Any]:
        """
        Return full system status.

        Returns:
            dict with balance, positions, daily_pnl, can_trade, latest_trades.
        """
        can_trade_reasons: List[str] = []

        daily_ok   = self.safety.check_daily_limit()
        leverage_ok = True  # checked per-signal; here we report overall
        if not daily_ok:
            can_trade_reasons.append(f"Daily loss limit hit (>{self.safety.max_daily_dd_pct}%)")

        can_trade = daily_ok and self._running

        return {
            "running":       self._running,
            "started_at":    self._started_at.isoformat() if self._started_at else None,
            "balance":       self._start_balance,
            "daily_pnl":     round(self._daily_pnl, 4),
            "open_positions": list(self._open_positions.values()),
            "can_trade":     can_trade,
            "reasons":       can_trade_reasons,
            "latest_trades": self._trade_history[-5:],
            "circuit_breaker": not daily_ok,
            "safety": {
                "max_daily_dd_pct": self.safety.max_daily_dd_pct,
                "max_leverage":     self.safety.max_leverage,
                "max_slippage_pct": self.safety.max_slippage_pct,
            },
        }
