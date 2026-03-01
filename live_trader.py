#!/usr/bin/env python3
"""
live_trader.py — LiveTrader: Real order execution on Hyperliquid (testnet/mainnet)
==================================================================================

Replaces PaperTrader when HL_SECRET_KEY + HL_WALLET_ADDRESS are set in .env.

Key capabilities:
  • Fetch REAL account balance from Hyperliquid margin account
  • Place MARKET orders (immediate fill at current price)
  • Place LIMIT orders with optional Stop-Loss / Take-Profit via HL trigger orders
  • Close open positions (market order in opposite direction)
  • DRY RUN mode: pre-flight validation only, zero orders sent
  • Full audit logging of every order attempt and result

Hyperliquid SDK reference:
  exchange.market_open(coin, is_buy, sz, px=None, slippage=0.05)
  exchange.market_close(coin, sz=None)  — closes full position by default
  exchange.order(coin, is_buy, sz, limit_px, order_type, reduce_only)
    order_type = {"limit": {"tif": "Gtc"}}                       # limit
    order_type = {"trigger": {"triggerPx": px, "isMarket": True, "tpsl": "sl"}}  # stop
    order_type = {"trigger": {"triggerPx": px, "isMarket": True, "tpsl": "tp"}}  # take profit

Usage:
    from live_trader import LiveTrader
    lt = LiveTrader()
    balance = lt.get_balance()
    result  = lt.place_order(signal, position_size_usd=100.0)
    lt.close_position("BTC")
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


# ============================================================================
# ORDER RESULT
# ============================================================================

@dataclass
class OrderResult:
    """Structured result from any order operation."""

    success: bool
    symbol: str
    side: str                    # "BUY" | "SELL"
    order_type: str              # "MARKET" | "LIMIT"
    size: float                  # crypto quantity
    price: float                 # fill price (market) or limit price
    order_id: Optional[str] = None
    sl_order_id: Optional[str] = None
    tp_order_id: Optional[str] = None
    error: Optional[str] = None
    raw_response: Optional[dict] = None
    timestamp: datetime = field(default_factory=datetime.now)
    dry_run: bool = False

    def __str__(self) -> str:
        status = "DRY-RUN" if self.dry_run else ("OK" if self.success else "FAILED")
        return (
            f"[{status}] {self.side} {self.size:.6f} {self.symbol} @ ${self.price:,.2f} "
            f"({self.order_type})"
            + (f" | OID={self.order_id}" if self.order_id else "")
            + (f" | ERR={self.error}" if self.error else "")
        )


# ============================================================================
# LIVE TRADER
# ============================================================================

class LiveTrader:
    """
    Real-money (or testnet) order execution via Hyperliquid SDK.

    Environment variables consumed (from .env):
        HL_SECRET_KEY       — Private key (hex, with or without 0x prefix)
        HL_WALLET_ADDRESS   — Public wallet address (0x...)
        HL_TESTNET          — "true" → testnet, "false" → mainnet  (default: true)
        HL_DRY_RUN          — "true" → validate only, no orders sent (default: false)

    Attributes:
        dry_run (bool): If True, all order calls validate params but never send.
    """

    def __init__(self, dry_run: bool = False):
        """
        Initialise LiveTrader.  Validates credentials immediately.

        Args:
            dry_run: Override DRY_RUN regardless of env var. If the env var
                     HL_DRY_RUN=true, dry_run is forced True.
        """
        self._secret_key = self._normalise_key(os.getenv("HL_SECRET_KEY", ""))
        self._wallet     = os.getenv("HL_WALLET_ADDRESS", "").strip()
        self._testnet    = os.getenv("HL_TESTNET", "true").lower() == "true"
        self.dry_run     = dry_run or (os.getenv("HL_DRY_RUN", "false").lower() == "true")

        self._info     = None
        self._exchange = None

        self._order_log: List[OrderResult] = []

        # Initialise clients (validates credentials)
        self._setup_clients()

    # ── Setup ────────────────────────────────────────────────────────────────

    @staticmethod
    def _normalise_key(key: str) -> str:
        """Ensure private key has 0x prefix."""
        key = key.strip()
        if key and not key.startswith("0x"):
            key = "0x" + key
        return key

    def _setup_clients(self):
        """Create Info (read-only) and Exchange (write) clients."""
        from hyperliquid.info import Info
        from hyperliquid.utils import constants

        url = constants.TESTNET_API_URL if self._testnet else constants.MAINNET_API_URL
        network_label = "TESTNET" if self._testnet else "MAINNET"

        logger.info("=" * 60)
        logger.info(f"LiveTrader initialising — {network_label}")
        logger.info(f"  Wallet:  {self._wallet}")
        logger.info(f"  DryRun:  {self.dry_run}")
        logger.info("=" * 60)

        self._info = Info(url, skip_ws=True)
        logger.info("✅ Info client ready")

        if not self._secret_key or self._secret_key == "0x":
            logger.warning("⚠️  No HL_SECRET_KEY — Exchange client DISABLED (read-only)")
            return

        if not self._wallet:
            logger.warning("⚠️  No HL_WALLET_ADDRESS — Exchange client DISABLED")
            return

        try:
            from eth_account import Account
            from hyperliquid.exchange import Exchange

            wallet_account = Account.from_key(self._secret_key)
            derived        = wallet_account.address

            if derived.lower() != self._wallet.lower():
                logger.error(
                    f"🔴 KEY/WALLET MISMATCH!\n"
                    f"   Key derives → {derived}\n"
                    f"   HL_WALLET_ADDRESS = {self._wallet}\n"
                    f"   Proceeding with derived address."
                )
                # Use the derived address (correct one) and log the discrepancy.
                # The SDK will use account_address for API requests.
                self._wallet = derived

            self._exchange = Exchange(
                wallet=wallet_account,
                base_url=url,
                account_address=self._wallet,
            )
            logger.info(f"✅ Exchange client ready — {network_label}")

        except Exception as exc:
            logger.error(f"❌ Exchange client failed: {exc}")
            self._exchange = None

    # ── Account info ─────────────────────────────────────────────────────────

    def get_balance(self) -> float:
        """
        Fetch real USD account balance from Hyperliquid margin account.

        Returns:
            Account value in USD, or 0.0 on error.
        """
        if not self._wallet:
            logger.error("get_balance: no wallet address configured")
            return 0.0
        try:
            state = self._info.user_state(self._wallet)
            value = float(state.get("marginSummary", {}).get("accountValue", 0))
            logger.info(f"💰 Real balance: ${value:,.2f} USD")
            return value
        except Exception as exc:
            logger.error(f"get_balance error: {exc}")
            return 0.0

    def get_positions(self) -> List[dict]:
        """
        Fetch all OPEN positions from Hyperliquid.

        Returns:
            List of position dicts: {symbol, size, entry_price, unrealized_pnl, leverage}
        """
        if not self._wallet:
            return []
        try:
            state = self._info.user_state(self._wallet)
            positions = []
            for p in state.get("assetPositions", []):
                raw = p["position"]
                sz  = float(raw["szi"])
                if sz != 0.0:
                    positions.append({
                        "symbol":         raw["coin"],
                        "size":           sz,
                        "entry_price":    float(raw.get("entryPx") or 0),
                        "unrealized_pnl": float(raw.get("unrealizedPnl") or 0),
                        "leverage":       raw.get("leverage", {}).get("value", 1),
                    })
            return positions
        except Exception as exc:
            logger.error(f"get_positions error: {exc}")
            return []

    def get_mark_price(self, symbol: str) -> Optional[float]:
        """Fetch current mark price for a symbol."""
        try:
            mids = self._info.all_mids()
            price_str = mids.get(symbol)
            if price_str is not None:
                return float(price_str)
            logger.warning(f"get_mark_price: {symbol} not found in mids")
            return None
        except Exception as exc:
            logger.error(f"get_mark_price error ({symbol}): {exc}")
            return None

    # ── Order helpers ─────────────────────────────────────────────────────────

    def _require_exchange(self) -> bool:
        """Check exchange client is ready. Logs error and returns False if not."""
        if self._exchange is None:
            logger.error("❌ Exchange client not initialised — cannot place orders")
            return False
        return True

    @staticmethod
    def _size_for_usd(usd: float, price: float, min_size: float = 0.001) -> float:
        """
        Convert USD notional to coin quantity.

        Args:
            usd:      USD position size (notional).
            price:    Current market price.
            min_size: Minimum order size (Hyperliquid enforces per-coin minimums).

        Returns:
            Rounded coin quantity (4 decimal places).
        """
        if price <= 0:
            return 0.0
        sz = round(usd / price, 4)
        return max(sz, min_size)

    # ── Core order placement ─────────────────────────────────────────────────

    def place_order(
        self,
        symbol: str,
        direction: str,          # "LONG" | "SHORT"
        size_usd: float,
        entry_price: float,
        stop_loss: Optional[float] = None,
        take_profit: Optional[float] = None,
        order_type: str = "MARKET",  # "MARKET" | "LIMIT"
    ) -> OrderResult:
        """
        Place a new position order on Hyperliquid.

        Args:
            symbol:      Coin symbol, e.g. "BTC".
            direction:   "LONG" (buy) or "SHORT" (sell).
            size_usd:    Notional position size in USD.
            entry_price: Expected entry price (used for size calc & limit orders).
            stop_loss:   Optional SL trigger price.
            take_profit: Optional TP trigger price.
            order_type:  "MARKET" or "LIMIT".

        Returns:
            OrderResult with success status and order details.
        """
        is_buy = direction == "LONG"
        side   = "BUY" if is_buy else "SELL"
        sz     = self._size_for_usd(size_usd, entry_price)

        logger.info(
            f"📋 ORDER REQUEST — {side} {sz:.4f} {symbol} @ ${entry_price:,.2f} "
            f"({order_type}) | SL={stop_loss} TP={take_profit}"
        )

        # DRY RUN — validate params only
        if self.dry_run:
            result = OrderResult(
                success=True, symbol=symbol, side=side, order_type=order_type,
                size=sz, price=entry_price, dry_run=True,
            )
            logger.info(f"🔵 DRY RUN: {result}")
            self._order_log.append(result)
            return result

        if not self._require_exchange():
            return OrderResult(
                success=False, symbol=symbol, side=side, order_type=order_type,
                size=sz, price=entry_price, error="Exchange client not ready",
            )

        try:
            close_is_buy = not is_buy  # for SL/TP (opposite direction)

            if order_type == "MARKET":
                # Step 1: Place market entry
                resp = self._exchange.market_open(
                    name=symbol,
                    is_buy=is_buy,
                    sz=sz,
                    slippage=0.05,
                )
            else:
                # LIMIT — Good-Till-Cancelled
                resp = self._exchange.order(
                    name=symbol,
                    is_buy=is_buy,
                    sz=sz,
                    limit_px=self._round_price(entry_price, 0),
                    order_type={"limit": {"tif": "Gtc"}},
                    reduce_only=False,
                )

            logger.debug(f"Raw exchange response: {resp}")

            # Parse entry response
            response = resp.get("response", {})
            data     = response.get("data", {})
            statuses = data.get("statuses", [{}])
            first    = statuses[0] if statuses else {}

            resting = first.get("resting", {})
            filled  = first.get("filled", {})
            error   = first.get("error", None)

            if error:
                result = OrderResult(
                    success=False, symbol=symbol, side=side, order_type=order_type,
                    size=sz, price=entry_price, error=str(error), raw_response=resp,
                )
                logger.error(f"❌ Order FAILED: {result}")
                self._order_log.append(result)
                return result

            oid        = resting.get("oid") or filled.get("oid")
            fill_price = float(filled.get("avgPx") or entry_price)

            result = OrderResult(
                success=True, symbol=symbol, side=side, order_type=order_type,
                size=sz, price=fill_price, order_id=str(oid) if oid else None,
                raw_response=resp,
            )
            logger.info(f"✅ {result}")

            # Step 2: Place SL/TP as positionTpsl (attached to open position)
            if stop_loss is not None or take_profit is not None:
                sl_oid, tp_oid = self._place_sl_tp(
                    symbol=symbol,
                    is_buy=is_buy,
                    sz=sz,
                    stop_loss=stop_loss,
                    take_profit=take_profit,
                )
                result.sl_order_id = sl_oid
                result.tp_order_id = tp_oid

            self._order_log.append(result)
            return result

        except Exception as exc:
            logger.exception(f"place_order exception ({symbol}): {exc}")
            result = OrderResult(
                success=False, symbol=symbol, side=side, order_type=order_type,
                size=sz, price=entry_price, error=str(exc),
            )
            self._order_log.append(result)
            return result

    def _place_sl_tp(
        self,
        symbol: str,
        is_buy: bool,
        sz: float,
        stop_loss: Optional[float],
        take_profit: Optional[float],
    ) -> tuple:
        """
        Place SL and/or TP trigger orders attached to an open position.

        Uses grouping="positionTpsl" which requires the position to be open.
        Returns (sl_oid, tp_oid) — either may be None on failure.
        """
        close_is_buy = not is_buy
        # limit_px for market-trigger orders must be within 80% of reference price.
        # For SELL triggers (closing LONG): set limit_px 10% BELOW trigger price.
        # For BUY  triggers (closing SHORT): set limit_px 10% ABOVE trigger price.
        def _worst_px(trigger: float) -> float:
            if not close_is_buy:   # SELL trigger
                return self._round_price(trigger * 0.9, 0)
            else:                  # BUY trigger
                return self._round_price(trigger * 1.1, 0)

        orders = []
        if stop_loss is not None:
            sl_px = self._round_price(stop_loss, 0)
            orders.append({
                "coin":       symbol,
                "is_buy":     close_is_buy,
                "sz":         sz,
                "limit_px":   _worst_px(sl_px),
                "order_type": {
                    "trigger": {"triggerPx": sl_px, "isMarket": True, "tpsl": "sl"}
                },
                "reduce_only": True,
            })
        if take_profit is not None:
            tp_px = self._round_price(take_profit, 0)
            orders.append({
                "coin":       symbol,
                "is_buy":     close_is_buy,
                "sz":         sz,
                "limit_px":   _worst_px(tp_px),
                "order_type": {
                    "trigger": {"triggerPx": tp_px, "isMarket": True, "tpsl": "tp"}
                },
                "reduce_only": True,
            })

        if not orders:
            return None, None

        logger.info(f"  📌 Placing SL/TP via positionTpsl ({len(orders)} orders)")
        try:
            resp = self._exchange.bulk_orders(
                order_requests=orders,
                grouping="positionTpsl",
            )
            logger.debug(f"  positionTpsl response: {resp}")

            statuses = resp.get("response", {}).get("data", {}).get("statuses", [])
            sl_oid = tp_oid = None
            idx = 0

            if stop_loss is not None and idx < len(statuses):
                st = statuses[idx]
                # Trigger orders return a string "waitingForTrigger" on success
                if st == "waitingForTrigger":
                    sl_oid = "trigger_ok"
                    logger.info(f"  ✅ SL queued (waitingForTrigger)")
                elif isinstance(st, dict):
                    err = st.get("error")
                    if err:
                        logger.warning(f"  ⚠️  SL failed: {err}")
                    else:
                        sl_oid = str(st.get("resting", {}).get("oid") or st.get("filled", {}).get("oid") or "trigger_ok")
                        logger.info(f"  ✅ SL placed OID={sl_oid}")
                idx += 1

            if take_profit is not None and idx < len(statuses):
                st = statuses[idx]
                if st == "waitingForTrigger":
                    tp_oid = "trigger_ok"
                    logger.info(f"  ✅ TP queued (waitingForTrigger)")
                elif isinstance(st, dict):
                    err = st.get("error")
                    if err:
                        logger.warning(f"  ⚠️  TP failed: {err}")
                    else:
                        tp_oid = str(st.get("resting", {}).get("oid") or st.get("filled", {}).get("oid") or "trigger_ok")
                        logger.info(f"  ✅ TP placed OID={tp_oid}")

            return sl_oid, tp_oid

        except Exception as exc:
            logger.error(f"  ❌ SL/TP placement failed: {exc}")
            return None, None

    @staticmethod
    def _round_price(price: float, decimals: int = 1) -> float:
        """Round price to the given decimal places (Hyperliquid tick-size safe)."""
        return round(price, decimals)

    def _place_stop(
        self,
        symbol: str,
        parent_is_buy: bool,  # True = parent was a BUY (LONG) → SL/TP is SELL
        sz: float,
        trigger_price: float,
        tpsl: str,            # "sl" | "tp"
    ) -> OrderResult:
        """
        Place a stop-loss or take-profit trigger order (reduce-only).

        For Hyperliquid trigger (market) orders:
          - `limit_px` = 0 when closing a LONG (selling)
          - `limit_px` = 999999 when closing a SHORT (buying)
          - `triggerPx` = rounded trigger price

        Args:
            symbol:        Coin symbol.
            parent_is_buy: Whether the parent order was a buy (long).
            sz:            Size to close.
            trigger_price: Price at which trigger fires.
            tpsl:          "sl" for stop-loss, "tp" for take-profit.
        """
        close_is_buy = not parent_is_buy   # close a LONG → SELL
        side_label   = "SL" if tpsl == "sl" else "TP"
        side_str     = "SELL" if not close_is_buy else "BUY"

        # Round to 1 dp to stay within Hyperliquid tick size for BTC/ETH
        trig_px  = self._round_price(trigger_price, 1)
        # For market triggers: limit_px acts as worst-case fill price
        # SELL trigger → limit_px very low (0 is invalid, use 1)
        # BUY  trigger → limit_px very high
        limit_px = 1.0 if not close_is_buy else 999_999.0

        logger.info(
            f"  📌 Placing {side_label} trigger @ ${trig_px:,.1f} "
            f"({side_str} {sz:.5f} {symbol}) limit_px={limit_px}"
        )

        try:
            # SL/TP must be sent with grouping="positionTpsl" so Hyperliquid
            # attaches them to the existing position. Exchange.order() defaults
            # to grouping="na" which is why standalone trigger orders fail.
            order_req = {
                "coin":       symbol,
                "is_buy":     close_is_buy,
                "sz":         sz,
                "limit_px":   limit_px,
                "order_type": {
                    "trigger": {
                        "triggerPx": trig_px,
                        "isMarket":  True,
                        "tpsl":      tpsl,
                    }
                },
                "reduce_only": True,
            }
            resp = self._exchange.bulk_orders(
                order_requests=[order_req],
                grouping="positionTpsl",
            )

            logger.debug(f"  {side_label} raw response: {resp}")

            statuses = resp.get("response", {}).get("data", {}).get("statuses", [{}])
            first    = statuses[0] if statuses else {}
            error    = first.get("error")
            oid      = first.get("resting", {}).get("oid") or first.get("filled", {}).get("oid")

            if error:
                return OrderResult(
                    success=False, symbol=symbol, side=side_str, order_type=side_label,
                    size=sz, price=trig_px, error=str(error),
                )

            return OrderResult(
                success=True, symbol=symbol, side=side_str, order_type=side_label,
                size=sz, price=trig_px, order_id=str(oid) if oid else None,
            )

        except Exception as exc:
            logger.error(f"  ❌ {side_label} order exception: {exc}")
            return OrderResult(
                success=False, symbol=symbol, side=side_str, order_type=side_label,
                size=sz, price=trig_px, error=str(exc),
            )

    def close_position(
        self,
        symbol: str,
        size: Optional[float] = None,
    ) -> OrderResult:
        """
        Close an open position via market order.

        Args:
            symbol: Coin symbol.
            size:   Size to close. None = close full position.

        Returns:
            OrderResult.
        """
        mark = self.get_mark_price(symbol)
        price = mark or 0.0

        logger.info(
            f"🔒 CLOSE REQUEST — {symbol} | size={size or 'full'} | mark=${price:,.2f}"
        )

        if self.dry_run:
            result = OrderResult(
                success=True, symbol=symbol, side="CLOSE", order_type="MARKET",
                size=size or 0.0, price=price, dry_run=True,
            )
            logger.info(f"🔵 DRY RUN close: {result}")
            self._order_log.append(result)
            return result

        if not self._require_exchange():
            return OrderResult(
                success=False, symbol=symbol, side="CLOSE", order_type="MARKET",
                size=0, price=0, error="Exchange not ready",
            )

        try:
            if size is not None:
                resp = self._exchange.market_close(coin=symbol, sz=size, slippage=0.05)
            else:
                resp = self._exchange.market_close(coin=symbol, slippage=0.05)

            logger.debug(f"close_position raw: {resp}")

            # market_close() returns None when no matching position exists
            # (e.g. already closed by TP/SL trigger or never opened on exchange)
            if resp is None:
                logger.warning(
                    f"⚠️  close_position({symbol}): market_close returned None — "
                    f"no open position found on exchange (may have been closed by TP/SL). "
                    f"Treating as success (position already closed)."
                )
                result = OrderResult(
                    success=True, symbol=symbol, side="CLOSE", order_type="MARKET",
                    size=size or 0, price=price,
                    error="No position on exchange (already closed?)",
                    raw_response=None,
                )
                self._order_log.append(result)
                return result

            response   = resp.get("response", {})
            data       = response.get("data", {})
            statuses   = data.get("statuses", [{}])
            first      = statuses[0] if statuses else {}
            error      = first.get("error")
            filled     = first.get("filled", {})
            fill_price = float(filled.get("avgPx") or price)
            oid        = filled.get("oid")

            if error:
                result = OrderResult(
                    success=False, symbol=symbol, side="CLOSE", order_type="MARKET",
                    size=size or 0, price=price, error=str(error), raw_response=resp,
                )
                logger.error(f"❌ Close FAILED: {result}")
            else:
                result = OrderResult(
                    success=True, symbol=symbol, side="CLOSE", order_type="MARKET",
                    size=size or 0, price=fill_price,
                    order_id=str(oid) if oid else None, raw_response=resp,
                )
                logger.info(f"✅ Position closed: {result}")

            self._order_log.append(result)
            return result

        except Exception as exc:
            logger.exception(f"close_position exception ({symbol}): {exc}")
            result = OrderResult(
                success=False, symbol=symbol, side="CLOSE", order_type="MARKET",
                size=0, price=price, error=str(exc),
            )
            self._order_log.append(result)
            return result

    # ── Audit log ────────────────────────────────────────────────────────────

    def get_order_log(self) -> List[OrderResult]:
        """Return all orders attempted this session."""
        return list(self._order_log)

    def print_order_log(self):
        """Print a formatted audit log of all orders."""
        print(f"\n{'='*60}")
        print(f"ORDER AUDIT LOG ({len(self._order_log)} entries)")
        print(f"{'='*60}")
        for i, r in enumerate(self._order_log, 1):
            ts = r.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            print(f"  {i:3d}. [{ts}] {r}")
        print(f"{'='*60}\n")

    # ── Convenience helpers ───────────────────────────────────────────────────

    def is_ready(self) -> bool:
        """True if the exchange client is ready to place orders."""
        return self._exchange is not None

    def network_label(self) -> str:
        return "TESTNET" if self._testnet else "MAINNET"


# ============================================================================
# STANDALONE TEST (run directly: python live_trader.py)
# ============================================================================

def _run_preflight():
    """Preflight checks: balance fetch + dry-run order + dry-run close."""
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    print("\n" + "="*60)
    print("LIVE TRADER — PRE-FLIGHT CHECK (DRY RUN)")
    print("="*60)

    lt = LiveTrader(dry_run=True)

    print(f"\n Network : {lt.network_label()}")
    print(f" Wallet  : {os.getenv('HL_WALLET_ADDRESS','(not set)')}")
    print(f" DryRun  : {lt.dry_run}")
    print(f" Ready   : {lt.is_ready()}")

    # 1. Balance
    print("\n[1] Fetching real balance ...")
    bal = lt.get_balance()
    print(f"    Balance: ${bal:,.2f} USD")

    # 2. Open positions
    print("\n[2] Fetching open positions ...")
    positions = lt.get_positions()
    if positions:
        for p in positions:
            print(f"    {p['symbol']}: size={p['size']} entry=${p['entry_price']:,.2f} "
                  f"PnL=${p['unrealized_pnl']:,.2f}")
    else:
        print("    No open positions")

    # 3. Mark price
    print("\n[3] Fetching BTC mark price ...")
    btc_price = lt.get_mark_price("BTC")
    print(f"    BTC mark price: ${btc_price:,.2f}")

    # 4. Dry-run LONG order
    print("\n[4] Dry-run: place LONG BTC order ($10 notional) ...")
    if btc_price:
        r = lt.place_order(
            symbol="BTC",
            direction="LONG",
            size_usd=10.0,
            entry_price=btc_price,
            stop_loss=btc_price * 0.995,
            take_profit=btc_price * 1.015,
        )
        print(f"    Result: {r}")

    # 5. Dry-run close
    print("\n[5] Dry-run: close BTC ...")
    r2 = lt.close_position("BTC")
    print(f"    Result: {r2}")

    lt.print_order_log()

    print("\n✅ Pre-flight complete. Set HL_DRY_RUN=false to place REAL orders.")
    return True


if __name__ == "__main__":
    _run_preflight()
