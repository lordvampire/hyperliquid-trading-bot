"""Hyperliquid SDK wrapper — abstracts testnet/mainnet connectivity."""

import time
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from config import cfg


def get_base_url() -> str:
    return constants.TESTNET_API_URL if cfg.HL_TESTNET else constants.MAINNET_API_URL


def get_info() -> Info:
    """Read-only info client (no key needed for public data)."""
    return Info(get_base_url(), skip_ws=True)


def get_exchange() -> Exchange | None:
    """Authenticated exchange client for placing orders. Returns None if no key.

    Bug #2 fix: SDK requires a LocalAccount object, not None.
    """
    if not cfg.HL_SECRET_KEY:
        return None
    wallet = Account.from_key(cfg.HL_SECRET_KEY)
    return Exchange(
        wallet=wallet,
        base_url=get_base_url(),
        account_address=cfg.HL_WALLET_ADDRESS or None,
    )


def fetch_balance(address: str = None) -> dict:
    """Fetch account balance + positions from Hyperliquid."""
    info = get_info()
    addr = address or cfg.HL_WALLET_ADDRESS
    if not addr:
        return {"error": "No wallet address configured"}
    try:
        state = info.user_state(addr)
        return {
            "address": addr,
            "testnet": cfg.HL_TESTNET,
            "account_value": state.get("marginSummary", {}).get("accountValue", "0"),
            "total_margin_used": state.get("marginSummary", {}).get("totalMarginUsed", "0"),
            "positions": [
                {
                    "symbol": p["position"]["coin"],
                    "size": p["position"]["szi"],
                    "entry_price": p["position"]["entryPx"],
                    "unrealized_pnl": p["position"]["unrealizedPnl"],
                    "leverage": p["position"]["leverage"]["value"],
                }
                for p in state.get("assetPositions", [])
                if float(p["position"]["szi"]) != 0
            ],
        }
    except Exception as e:
        return {"error": str(e)}


def fetch_candles(symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
    """Fetch OHLCV candles from Hyperliquid.

    Bug #1 fix: SDK signature is candles_snapshot(name, interval, startTime, endTime).
    We compute startTime from limit and pass endTime correctly.
    """
    info = get_info()
    end_time = int(time.time() * 1000)
    # Estimate startTime based on interval and limit
    interval_ms_map = {
        "1m": 60_000, "5m": 300_000, "15m": 900_000,
        "30m": 1_800_000, "1h": 3_600_000, "4h": 14_400_000,
        "1d": 86_400_000,
    }
    interval_ms = interval_ms_map.get(interval, 3_600_000)
    start_time = end_time - (limit * interval_ms)
    candles = info.candles_snapshot(symbol, interval, start_time, end_time)
    return candles
