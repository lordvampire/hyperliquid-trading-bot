"""Tests for FastAPI endpoints — bugs #4, #5, #6, #8."""

import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    # Patch exchange calls so we don't hit real API
    with patch("main.fetch_balance", return_value={"account_value": "10000", "total_margin_used": "0", "positions": []}):
        with patch("main.risk_manager") as mock_rm:
            mock_rm.starting_balance = 10000.0
            mock_rm.can_trade.return_value = (True, "OK")
            mock_rm.get_position_size.return_value = 200.0
            mock_rm.status.return_value = {
                "starting_balance": 10000, "current_balance": 10000,
                "daily_pnl": 0, "daily_dd_pct": 0, "consecutive_losses": 0,
                "circuit_breaker_active": False, "can_trade": True, "reason": "OK",
            }
            mock_rm.load_state = MagicMock()
            from main import app
            yield TestClient(app, raise_server_exceptions=False)


def test_health_returns_healthy(client):
    """Bug #4: /health should return 'healthy' not 'ok'."""
    with patch("main.cfg") as mock_cfg:
        mock_cfg.validate.return_value = []
        mock_cfg.HL_TESTNET = True
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


def test_order_returns_202(client):
    """Bug #5: POST /order should return 202."""
    resp = client.post("/order", json={
        "symbol": "BTC", "side": "buy", "size": 0.1, "order_type": "market"
    })
    assert resp.status_code == 202
    assert resp.json()["message"] == "order queued"


def test_candles_bad_interval(client):
    """Bug #6: Bad interval should return 400, not 200 with error."""
    resp = client.get("/candles?symbol=BTC&interval=invalid")
    assert resp.status_code == 400


def test_candles_bad_limit(client):
    """Bug #6: limit out of range should return 400."""
    resp = client.get("/candles?symbol=BTC&limit=0")
    assert resp.status_code == 400


def test_cors_headers(client):
    """Bug #8: CORS should be present for localhost origins."""
    resp = client.options("/health", headers={
        "Origin": "http://localhost:3000",
        "Access-Control-Request-Method": "GET",
    })
    # CORS middleware should respond
    assert resp.status_code in (200, 204)
