#!/usr/bin/env python3
"""
test_live_order.py — Real testnet order test.
Sends a LIVE BTC market order on Hyperliquid testnet, then immediately closes it.
Run with: python test_live_order.py
"""
import os
import time
import logging
from dotenv import load_dotenv

load_dotenv()
os.environ["HL_DRY_RUN"] = "false"  # ensure live mode

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

from live_trader import LiveTrader

def main():
    lt = LiveTrader(dry_run=False)
    print(f"\n{'='*60}")
    print(f"LIVE ORDER TEST — {lt.network_label()}")
    print(f"{'='*60}")
    print(f"  Ready: {lt.is_ready()}")

    # 1. Balance
    bal = lt.get_balance()
    print(f"\n[1] Balance: ${bal:,.2f} USD")
    if bal == 0:
        print("  ⚠️  Zero balance — check wallet address / testnet funding")

    # 2. Mark price
    price = lt.get_mark_price("BTC")
    print(f"[2] BTC mark price: ${price:,.2f}")

    # 3. Place tiny LONG ($5 notional)
    print(f"\n[3] Placing LIVE LONG BTC ($5 notional) ...")
    result = lt.place_order(
        symbol="BTC",
        direction="LONG",
        size_usd=5.0,
        entry_price=price,
        stop_loss=price * 0.995,
        take_profit=price * 1.015,
        order_type="MARKET",
    )
    print(f"    Result : {result}")
    print(f"    Success: {result.success}")
    print(f"    OID    : {result.order_id}")
    print(f"    SL OID : {result.sl_order_id}")
    print(f"    TP OID : {result.tp_order_id}")
    print(f"    Fill $ : ${result.price:,.2f}")
    if result.error:
        print(f"    Error  : {result.error}")

    if not result.success:
        print("\n❌ Order failed — aborting close test")
        lt.print_order_log()
        return

    # 4. Verify via positions endpoint
    time.sleep(3)
    print("\n[4] Open positions after order:")
    positions = lt.get_positions()
    if positions:
        for p in positions:
            print(f"    {p['symbol']}: sz={p['size']} entry=${p['entry_price']:,.2f} "
                  f"PnL=${p['unrealized_pnl']:,.2f}")
    else:
        print("    (none — may need a moment to settle)")

    # 5. Close
    print(f"\n[5] Closing BTC position ...")
    close = lt.close_position("BTC")
    print(f"    Result : {close}")
    print(f"    Success: {close.success}")
    print(f"    Fill $ : ${close.price:,.2f}")
    if close.error:
        print(f"    Error  : {close.error}")

    # 6. Balance after
    time.sleep(2)
    bal2 = lt.get_balance()
    print(f"\n[6] Balance after: ${bal2:,.2f} USD  (Δ {bal2-bal:+.4f})")

    lt.print_order_log()
    print("✅ Live order test complete.")

if __name__ == "__main__":
    main()
