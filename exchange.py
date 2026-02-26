"""Hyperliquid SDK wrapper — abstracts testnet/mainnet connectivity."""

import time
import logging
from eth_account import Account
from hyperliquid.info import Info
from hyperliquid.exchange import Exchange
from hyperliquid.utils import constants
from config import cfg

# Setup logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def get_base_url() -> str:
    url = constants.TESTNET_API_URL if cfg.HL_TESTNET else constants.MAINNET_API_URL
    logger.info(f"🌐 Hyperliquid URL: {url} (testnet={cfg.HL_TESTNET})")
    return url


def validate_config() -> dict:
    """Debug: Validate all configuration."""
    issues = []
    
    logger.debug("=" * 60)
    logger.debug("🔍 CONFIG VALIDATION")
    logger.debug("=" * 60)
    
    # 1. Check Testnet setting
    logger.info(f"HL_TESTNET = {cfg.HL_TESTNET}")
    if not cfg.HL_TESTNET:
        issues.append("⚠️  MAINNET MODE — using LIVE money!")
    
    # 2. Check Wallet Address
    if not cfg.HL_WALLET_ADDRESS:
        issues.append("❌ HL_WALLET_ADDRESS is empty/missing!")
        logger.error("❌ HL_WALLET_ADDRESS not set!")
    else:
        logger.info(f"✅ HL_WALLET_ADDRESS = {cfg.HL_WALLET_ADDRESS}")
        if not cfg.HL_WALLET_ADDRESS.startswith("0x"):
            issues.append(f"❌ HL_WALLET_ADDRESS should start with '0x', got: {cfg.HL_WALLET_ADDRESS[:10]}")
        if len(cfg.HL_WALLET_ADDRESS) != 42:
            issues.append(f"❌ HL_WALLET_ADDRESS wrong length (should be 42 chars), got: {len(cfg.HL_WALLET_ADDRESS)}")
    
    # 3. Check Secret Key
    if not cfg.HL_SECRET_KEY:
        issues.append("❌ HL_SECRET_KEY is empty/missing!")
        logger.error("❌ HL_SECRET_KEY not set!")
    else:
        logger.info(f"✅ HL_SECRET_KEY = {cfg.HL_SECRET_KEY[:20]}... (redacted)")
        if not cfg.HL_SECRET_KEY.startswith("0x"):
            issues.append(f"❌ HL_SECRET_KEY should start with '0x', got: {cfg.HL_SECRET_KEY[:10]}")
        if len(cfg.HL_SECRET_KEY) != 66:
            issues.append(f"❌ HL_SECRET_KEY wrong length (should be 66 chars), got: {len(cfg.HL_SECRET_KEY)}")
        
        # Try to load account
        try:
            account = Account.from_key(cfg.HL_SECRET_KEY)
            account_address = account.address
            logger.info(f"✅ Private Key valid! Account address: {account_address}")
            
            # Check if account matches wallet address
            if account_address.lower() != cfg.HL_WALLET_ADDRESS.lower():
                issues.append(
                    f"⚠️  ACCOUNT MISMATCH!\n"
                    f"   Private Key derives from: {account_address}\n"
                    f"   But HL_WALLET_ADDRESS is: {cfg.HL_WALLET_ADDRESS}\n"
                    f"   These MUST match!"
                )
                logger.error(f"⚠️  MISMATCH: Key={account_address}, Config={cfg.HL_WALLET_ADDRESS}")
        except Exception as e:
            issues.append(f"❌ Private Key invalid: {e}")
            logger.error(f"❌ Cannot load private key: {e}")
    
    logger.debug("=" * 60)
    if issues:
        logger.error(f"❌ Found {len(issues)} configuration issues:")
        for issue in issues:
            logger.error(f"   {issue}")
    else:
        logger.info("✅ All config checks passed!")
    logger.debug("=" * 60)
    
    return {"issues": issues, "testnet": cfg.HL_TESTNET}


def get_info() -> Info:
    """Read-only info client (no key needed for public data)."""
    logger.debug("📡 Creating Info client (read-only)...")
    try:
        client = Info(get_base_url(), skip_ws=True)
        logger.info("✅ Info client created successfully")
        return client
    except Exception as e:
        logger.error(f"❌ Failed to create Info client: {e}")
        raise


def get_exchange() -> Exchange | None:
    """Authenticated exchange client for placing orders. Returns None if no key.

    Bug #2 fix: SDK requires a LocalAccount object, not None.
    """
    if not cfg.HL_SECRET_KEY:
        logger.warning("⚠️  No HL_SECRET_KEY — Exchange client disabled (read-only mode)")
        return None
    
    logger.debug("🔑 Creating Exchange client (with authentication)...")
    try:
        wallet = Account.from_key(cfg.HL_SECRET_KEY)
        logger.info(f"✅ Wallet loaded: {wallet.address}")
        
        exchange = Exchange(
            wallet=wallet,
            base_url=get_base_url(),
            account_address=cfg.HL_WALLET_ADDRESS or None,
        )
        logger.info("✅ Exchange client created successfully")
        return exchange
    except Exception as e:
        logger.error(f"❌ Failed to create Exchange client: {e}")
        return None


def fetch_balance(address: str = None) -> dict:
    """Fetch account balance + positions from Hyperliquid."""
    addr = address or cfg.HL_WALLET_ADDRESS
    
    logger.debug(f"💰 Fetching balance for: {addr}")
    
    if not addr:
        logger.error("❌ No wallet address configured!")
        return {"error": "No wallet address configured"}
    
    try:
        info = get_info()
        logger.debug(f"📡 Querying Hyperliquid API...")
        
        state = info.user_state(addr)
        
        logger.debug(f"✅ API response received")
        logger.debug(f"   Raw state keys: {state.keys()}")
        
        account_value = state.get("marginSummary", {}).get("accountValue", "0")
        total_margin = state.get("marginSummary", {}).get("totalMarginUsed", "0")
        positions = state.get("assetPositions", [])
        
        logger.info(f"✅ Balance: {account_value} USD (used margin: {total_margin})")
        logger.info(f"   Positions: {len([p for p in positions if float(p['position']['szi']) != 0])} open")
        
        result = {
            "address": addr,
            "testnet": cfg.HL_TESTNET,
            "account_value": account_value,
            "total_margin_used": total_margin,
            "positions": [
                {
                    "symbol": p["position"]["coin"],
                    "size": p["position"]["szi"],
                    "entry_price": p["position"]["entryPx"],
                    "unrealized_pnl": p["position"]["unrealizedPnl"],
                    "leverage": p["position"]["leverage"]["value"],
                }
                for p in positions
                if float(p["position"]["szi"]) != 0
            ],
        }
        logger.debug(f"📦 Returning balance data")
        return result
        
    except Exception as e:
        logger.error(f"❌ Error fetching balance: {e}")
        logger.debug(f"   Exception type: {type(e).__name__}")
        import traceback
        logger.debug(f"   Traceback:\n{traceback.format_exc()}")
        return {"error": str(e), "address": addr}


def fetch_candles(symbol: str, interval: str = "1h", limit: int = 100) -> list[dict]:
    """Fetch OHLCV candles from Hyperliquid.

    Bug #1 fix: SDK signature is candles_snapshot(name, interval, startTime, endTime).
    We compute startTime from limit and pass endTime correctly.
    """
    logger.debug(f"📊 Fetching {limit} {interval} candles for {symbol}...")
    
    try:
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
        
        logger.debug(f"   start_time: {start_time}, end_time: {end_time}")
        
        candles = info.candles_snapshot(symbol, interval, start_time, end_time)
        
        logger.info(f"✅ Fetched {len(candles)} candles for {symbol}")
        return candles
        
    except Exception as e:
        logger.error(f"❌ Error fetching candles for {symbol}: {e}")
        logger.debug(f"   Exception type: {type(e).__name__}")
        import traceback
        logger.debug(f"   Traceback:\n{traceback.format_exc()}")
        return []
