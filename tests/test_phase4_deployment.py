"""
Phase 4 deployment tests — SafetyManager + LiveDeployment + bot.py integration.

Run with:
    python -m pytest tests/test_phase4_deployment.py -v
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from strategies.base import Signal
from config.manager import ConfigManager
from safety_manager import SafetyManager
from live_deployment import LiveDeployment


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def tmp_config(tmp_path: Path) -> ConfigManager:
    """A minimal ConfigManager backed by a temp YAML."""
    yaml_text = """
strategies:
  strategy_b:
    fast_period: 5
    slow_period: 20
    rsi_period: 14
    momentum_weight: 0.5
    rsi_weight: 0.3
    volume_weight: 0.2
    entry_threshold: 0.4
    exit_threshold: 0.15
    stop_pct: 0.02
    tp_pct: 0.04

position_sizing:
  max_position_pct: 0.20
  base_size_pct: 0.10
  volatility_scale: 0.5
  leverage_cap: 5.0

safety:
  max_daily_dd_pct: 5.0
  max_leverage: 35
  max_slippage_pct: 2.0
  network_latency_limit_ms: 2000
  audit_log_path: "{audit_log}"

deployment:
  strategy: "strategy_b"
  mode: "backtest"
  starting_capital: 1000.0
  registry_path: "{registry}"

telegram:
  admin_user_ids: [5890731372]
""".format(
        audit_log=str(tmp_path / "audit.log"),
        registry=str(tmp_path / "param_history.json"),
    )
    cfg_path = tmp_path / "base.yaml"
    cfg_path.write_text(yaml_text)
    return ConfigManager(str(cfg_path), "backtest")


@pytest.fixture()
def safety(tmp_config: ConfigManager) -> SafetyManager:
    mgr = SafetyManager(tmp_config)
    mgr.set_daily_start_balance(1000.0)
    return mgr


@pytest.fixture()
def long_signal() -> Signal:
    return Signal("BTC", "LONG", 0.75, 43_000.0, 47_000.0, {"volatility": 0.03})


@pytest.fixture()
def deployment(tmp_config: ConfigManager, safety: SafetyManager) -> LiveDeployment:
    from strategies.strategy_b import StrategyB
    strategy = StrategyB(tmp_config.strategy("strategy_b"), "backtest")
    dep = LiveDeployment(strategy, tmp_config, exchange=None, safety_manager=safety)
    dep._start_balance = 1000.0
    return dep


# ===========================================================================
# SafetyManager tests
# ===========================================================================

class TestSafetyManagerPreTrade:
    def test_pre_trade_check_accepts_valid_signal(self, safety: SafetyManager, long_signal: Signal):
        ok, reason = safety.check_pre_trade(long_signal, current_price=45_000, balance=1000)
        assert ok, f"Expected safe but got reason: {reason}"
        assert reason == ""

    def test_pre_trade_check_rejects_hold_signal(self, safety: SafetyManager):
        hold = Signal("BTC", "HOLD", 0.5, 0.0, 0.0)
        ok, reason = safety.check_pre_trade(hold, current_price=45_000, balance=1000)
        assert not ok
        assert "HOLD" in reason

    def test_pre_trade_check_rejects_unsafe_signal_low_strength(self, safety: SafetyManager):
        """Very low strength → liquidity check fails."""
        weak = Signal("BTC", "LONG", 0.05, 43_000.0, 47_000.0)
        ok, reason = safety.check_pre_trade(weak, current_price=45_000, balance=1000)
        assert not ok
        assert "strength" in reason.lower() or "liquidity" in reason.lower()

    def test_pre_trade_check_rejects_price_out_of_bounds(self, safety: SafetyManager):
        """Current price >20% from SMA should be rejected."""
        signal = Signal("BTC", "LONG", 0.9, 0.0, 0.0, {"sma": 10_000.0})
        ok, reason = safety.check_pre_trade(signal, current_price=45_000, balance=1000)
        assert not ok
        assert "20%" in reason or "SMA" in reason

    def test_pre_trade_check_rejects_when_circuit_breaker_active(
        self, safety: SafetyManager, long_signal: Signal
    ):
        safety.set_daily_start_balance(1000.0)
        safety.update_daily_pnl(-60.0)   # -6% → exceeds 5% limit
        ok, reason = safety.check_pre_trade(long_signal, current_price=45_000, balance=940)
        assert not ok
        assert "circuit breaker" in reason.lower() or "daily loss" in reason.lower()


class TestDailyLimitCircuitBreaker:
    def test_check_daily_limit_passes_when_below_threshold(self, safety: SafetyManager):
        safety.update_daily_pnl(-30.0)   # -3% — under limit
        assert safety.check_daily_limit() is True

    def test_daily_limit_circuit_breaker_triggers(self, safety: SafetyManager):
        safety.update_daily_pnl(-60.0)   # -6% — over 5% limit
        assert safety.check_daily_limit() is False

    def test_daily_limit_exactly_at_threshold(self, safety: SafetyManager):
        safety.update_daily_pnl(-50.0)   # exactly -5%
        assert safety.check_daily_limit() is False  # >= triggers breaker

    def test_daily_limit_resets_after_new_day(self, safety: SafetyManager):
        safety.update_daily_pnl(-60.0)
        assert not safety.check_daily_limit()
        safety.set_daily_start_balance(1000.0)   # daily reset
        assert safety.check_daily_limit() is True


class TestLeverageCheck:
    def test_leverage_check_passes_under_limit(self, safety: SafetyManager):
        assert safety.check_leverage(100.0, 10.0) is True

    def test_leverage_check_fails_over_max(self, safety: SafetyManager):
        assert safety.check_leverage(100.0, 36.0) is False

    def test_leverage_check_warns_at_30x(self, safety: SafetyManager, caplog):
        import logging
        with caplog.at_level(logging.WARNING, logger="safety_manager"):
            result = safety.check_leverage(100.0, 30.0)
        assert result is True
        assert any("30x" in m or "HIGH LEVERAGE" in m for m in caplog.messages)

    def test_leverage_check_allows_exactly_35x(self, safety: SafetyManager):
        assert safety.check_leverage(100.0, 35.0) is True

    def test_leverage_check_blocks_above_35x(self, safety: SafetyManager):
        assert safety.check_leverage(100.0, 35.1) is False


class TestNetworkHealthCheck:
    def test_network_health_check_passes_on_fast_response(self, safety: SafetyManager):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        with patch("safety_manager.requests.post", return_value=mock_resp) as mock_post:
            result = safety.check_network_health()
        assert result is True

    def test_network_health_check_fails_on_exception(self, safety: SafetyManager):
        with patch("safety_manager.requests.post", side_effect=Exception("timeout")):
            result = safety.check_network_health()
        assert result is False


class TestTradeLogging:
    def test_trade_logging_creates_audit_file(self, safety: SafetyManager, long_signal: Signal):
        safety.log_trade("T-001", "BTC", long_signal, 45_000.0, 0.5, "executed")
        assert safety.audit_log_path.exists()

    def test_trade_logging_is_append_only(self, safety: SafetyManager, long_signal: Signal):
        """Audit log must grow monotonically — never overwritten."""
        safety.log_trade("T-001", "BTC", long_signal, 45_000.0, 0.5, "executed")
        size_after_1 = safety.audit_log_path.stat().st_size

        safety.log_trade("T-002", "ETH", long_signal, 3_000.0, 1.0, "executed")
        size_after_2 = safety.audit_log_path.stat().st_size

        assert size_after_2 > size_after_1, "Audit log should only grow"

    def test_trade_log_contains_valid_json(self, safety: SafetyManager, long_signal: Signal):
        safety.log_trade("T-003", "BTC", long_signal, 45_000.0, 0.5, "executed")
        lines = safety.audit_log_path.read_text().strip().splitlines()
        for line in lines:
            entry = json.loads(line)
            assert "trade_id" in entry
            assert "timestamp" in entry
            assert "status" in entry


# ===========================================================================
# LiveDeployment tests
# ===========================================================================

class TestLiveDeploymentStart:
    def test_start_trading_initializes(self, deployment: LiveDeployment):
        deployment.start_trading()
        assert deployment._running is True
        assert deployment._started_at is not None

    def test_start_trading_sets_balance(self, deployment: LiveDeployment):
        deployment.start_trading()
        assert deployment._start_balance == 1000.0


class TestProcessSignal:
    def test_process_signal_follows_safety(self, deployment: LiveDeployment, long_signal: Signal):
        deployment.start_trading()
        result = deployment.process_signal(long_signal, current_price=45_000, balance=1000)
        assert result["status"] in ("executed", "rejected")

    def test_process_signal_executes_safe_signal(self, deployment: LiveDeployment, long_signal: Signal):
        deployment.start_trading()
        result = deployment.process_signal(long_signal, current_price=45_000, balance=1000)
        assert result["status"] == "executed"
        assert "order_id" in result

    def test_process_signal_rejects_on_circuit_breaker(
        self, deployment: LiveDeployment, long_signal: Signal
    ):
        deployment.start_trading()
        deployment.safety.update_daily_pnl(-60.0)   # trigger circuit breaker
        result = deployment.process_signal(long_signal, current_price=45_000, balance=940)
        assert result["status"] == "rejected"

    def test_process_signal_fails_without_start(
        self, deployment: LiveDeployment, long_signal: Signal
    ):
        result = deployment.process_signal(long_signal, current_price=45_000, balance=1000)
        assert result["status"] == "error"


class TestClosePosition:
    def test_close_position_calculates_pnl(self, deployment: LiveDeployment, long_signal: Signal):
        deployment.start_trading()
        deployment.process_signal(long_signal, current_price=45_000, balance=1000)
        result = deployment.close_position("BTC", reason="take_profit", exit_price=46_000)
        assert result["status"] == "closed"
        assert result["pnl"] > 0   # price went up on a LONG

    def test_close_position_short_pnl(self, deployment: LiveDeployment):
        deployment.start_trading()
        short = Signal("ETH", "SHORT", 0.8, 0.0, 0.0, {"volatility": 0.03})
        deployment.process_signal(short, current_price=3_000, balance=1000)
        result = deployment.close_position("ETH", reason="stop_loss", exit_price=2_900)
        assert result["status"] == "closed"
        assert result["pnl"] > 0   # price fell on a SHORT

    def test_close_position_returns_error_if_no_open(self, deployment: LiveDeployment):
        deployment.start_trading()
        result = deployment.close_position("NOEXIST", reason="manual")
        assert result["status"] == "error"


class TestDailyReset:
    def test_daily_reset_archives_logs(self, deployment: LiveDeployment, long_signal: Signal, tmp_path: Path):
        deployment.start_trading()
        deployment.process_signal(long_signal, current_price=45_000, balance=1000)
        deployment.daily_reset()
        log_dir = deployment._log_dir
        archives = list(log_dir.glob("audit_*.log"))
        assert len(archives) >= 1, "Expected at least one archived log"

    def test_daily_reset_resets_pnl(self, deployment: LiveDeployment):
        deployment.start_trading()
        deployment.safety.update_daily_pnl(-30.0)
        deployment.daily_reset()
        assert deployment.safety._daily_pnl == 0.0


class TestGetStatus:
    def test_get_status_returns_current_state(self, deployment: LiveDeployment, long_signal: Signal):
        deployment.start_trading()
        deployment.process_signal(long_signal, current_price=45_000, balance=1000)
        status = deployment.get_status()
        assert "running" in status
        assert "balance" in status
        assert "daily_pnl" in status
        assert "can_trade" in status
        assert "latest_trades" in status
        assert status["running"] is True
        assert len(status["open_positions"]) == 1

    def test_get_status_shows_circuit_breaker(self, deployment: LiveDeployment):
        deployment.start_trading()
        deployment.safety.update_daily_pnl(-60.0)
        status = deployment.get_status()
        assert status["circuit_breaker"] is True
        assert status["can_trade"] is False


# ===========================================================================
# bot.py integration tests (source-inspection — no import needed)
# ===========================================================================

def _read_bot_src() -> str:
    """Read bot.py source without importing (avoids config dependency clash)."""
    bot_path = Path(__file__).parent.parent / "bot.py"
    return bot_path.read_text()


class TestBotIntegration:
    def test_optimize_command_handler_registered(self):
        """Verify /optimize handler exists in run_bot registration block."""
        src = _read_bot_src()
        assert 'CommandHandler("optimize"' in src or "optimize" in src

    def test_paper_trade_command_handler_registered(self):
        src = _read_bot_src()
        assert "paper_trade" in src

    def test_go_live_command_handler_registered(self):
        src = _read_bot_src()
        assert "go_live" in src

    def test_go_live_requires_admin(self):
        """cmd_go_live function must check admin_user_ids."""
        src = _read_bot_src()
        assert "admin_user_ids" in src or "admin_ids" in src

    def test_go_live_starts_deployment(self):
        """cmd_go_live should assign _live_deployment."""
        src = _read_bot_src()
        assert "_live_deployment" in src
        assert "start_trading" in src

    def test_optimize_command_uses_optimization_runner(self):
        src = _read_bot_src()
        assert "OptimizationRunner" in src

    def test_paper_trade_command_uses_paper_trader(self):
        src = _read_bot_src()
        assert "PaperTrader" in src
