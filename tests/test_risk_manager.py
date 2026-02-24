"""Unit tests for RiskManager — DD cap, circuit breaker, sizing."""

import pytest
from manager import RiskManager


@pytest.fixture
def rm():
    rm = RiskManager(max_daily_dd_pct=5.0, max_consecutive_losses=3, default_size_pct=2.0, db_path=":memory:")
    rm.reset_day(10000.0)
    return rm


def test_initial_state(rm):
    assert rm.can_trade() == (True, "OK")
    assert rm.starting_balance == 10000.0
    assert rm.daily_pnl == 0.0


def test_winning_trades(rm):
    rm.record_trade(100)
    rm.record_trade(50)
    assert rm.consecutive_losses == 0
    assert rm.daily_pnl == 150
    assert rm.can_trade() == (True, "OK")


def test_circuit_breaker_triggers(rm):
    rm.record_trade(-50)
    rm.record_trade(-50)
    assert rm.can_trade()[0] is True  # 2 losses, not yet 3
    rm.record_trade(-50)
    assert rm.circuit_breaker_active is True
    allowed, reason = rm.can_trade()
    assert allowed is False
    assert "Circuit breaker" in reason


def test_circuit_breaker_resets_on_win(rm):
    rm.record_trade(-50)
    rm.record_trade(-50)
    rm.record_trade(100)  # win resets streak
    assert rm.consecutive_losses == 0
    assert rm.can_trade()[0] is True


def test_daily_dd_cap(rm):
    # 5% of 10000 = 500
    rm.record_trade(-400)
    assert rm.can_trade()[0] is True
    rm.record_trade(-100)  # total -500 = exactly -5%
    allowed, reason = rm.can_trade()
    assert allowed is False
    assert "DD cap" in reason


def test_position_sizing(rm):
    assert rm.get_position_size() == 200.0  # 2% of 10000
    assert rm.get_position_size(5000) == 100.0  # 2% of 5000


def test_reset_day(rm):
    rm.record_trade(-100)
    rm.record_trade(-100)
    rm.record_trade(-100)
    assert rm.circuit_breaker_active is True
    rm.reset_day(9700)
    assert rm.circuit_breaker_active is False
    assert rm.consecutive_losses == 0
    assert rm.starting_balance == 9700


def test_status_output(rm):
    s = rm.status()
    assert "can_trade" in s
    assert "daily_pnl" in s
    assert "circuit_breaker_active" in s
