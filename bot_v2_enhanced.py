#!/usr/bin/env python3
"""
Enhanced Telegram Bot with Live Signal Monitoring
Shows real-time analysis and periodic updates
"""

import asyncio
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError

from config import cfg
from exchange import fetch_balance, fetch_candles
from manager import RiskManager

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Risk manager
risk_manager = RiskManager(
    max_daily_dd_pct=cfg.RISK_MAX_DAILY_DD_PCT,
    max_consecutive_losses=cfg.RISK_MAX_CONSECUTIVE_LOSSES,
    default_size_pct=cfg.RISK_DEFAULT_SIZE_PCT,
    db_path=cfg.DB_PATH,
)

# Bot state
class BotState:
    def __init__(self):
        self.last_signals = {}  # Store last signals {symbol: {signal, timestamp}}
        self.analysis_running = False
        self.update_interval = 1800  # 30 minutes

bot_state = BotState()

def format_status(bal: dict, risk: dict) -> str:
    """Format status message"""
    if "error" in bal:
        return f"⚠️ Error: {bal['error']}"

    net = "🟢 TESTNET" if cfg.HL_TESTNET else "🔴 MAINNET"
    positions = bal.get("positions", [])
    pos_text = "No open positions"
    if positions:
        lines = []
        for p in positions[:3]:  # Max 3 shown
            pnl = float(p.get("unrealized_pnl", 0))
            emoji = "🟢" if pnl >= 0 else "🔴"
            lines.append(f"  {emoji} {p.get('symbol')}: {p.get('size')} (PnL: ${pnl:.2f})")
        pos_text = "\n".join(lines)
        if len(positions) > 3:
            pos_text += f"\n  ... +{len(positions)-3} more"

    can_trade = "✅ Yes" if risk.get("can_trade") else f"❌ No"

    return (
        f"📊 *Trading Bot Status* {net}\n"
        f"🕐 Updated: {datetime.now().strftime('%H:%M:%S')}\n\n"
        f"💰 Account Value: ${float(bal.get('account_value', 0)):,.2f}\n"
        f"📈 Margin Used: ${float(bal.get('total_margin_used', 0)):,.2f}\n\n"
        f"*Positions:*\n{pos_text}\n\n"
        f"*Risk Status:*\n"
        f"  Daily P&L: ${risk.get('daily_pnl', 0):,.2f} ({risk.get('daily_dd_pct', 0):.2f}%)\n"
        f"  Losses: {risk.get('consecutive_losses', 0)}/{risk_manager.max_consecutive_losses}\n"
        f"  Can Trade: {can_trade}\n\n"
        f"⏱️ Next update: /live for real-time analysis"
    )

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command"""
    msg = (
        "🤖 *Hyperliquid Trading Bot v2*\n\n"
        "Available commands:\n"
        "  /help — Show this menu + detailed explanations\n"
        "  /status — Account + risk overview\n"
        "  /balance — Quick balance check\n"
        "  /risk — Detailed risk metrics\n"
        "  /signals — Last generated signals\n"
        "  /live — Start 30min live monitoring\n"
        "  /analyze [BTC|ETH|SOL] — Analyze symbol now\n\n"
        "🎮 Testnet Mode Active\n"
        "Type /help for detailed guide!"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command with detailed explanations"""
    msg = (
        "📚 *Hyperliquid Trading Bot - Command Guide*\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*📊 STATUS & MONITORING COMMANDS*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/status**\n"
        "Shows complete bot status:\n"
        "  • Account value (balance)\n"
        "  • Margin used\n"
        "  • Open positions\n"
        "  • Daily P&L\n"
        "  • Can trade? (yes/no)\n"
        "Usage: `/status`\n\n"
        
        "**/balance**\n"
        "Quick balance check without all the details\n"
        "Usage: `/balance`\n\n"
        
        "**/risk**\n"
        "See detailed risk management status:\n"
        "  • Daily P&L (profit/loss)\n"
        "  • Daily loss limit (-5%)\n"
        "  • Consecutive losses\n"
        "  • Circuit breaker status\n"
        "Usage: `/risk`\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*📈 SIGNAL & ANALYSIS COMMANDS*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/signals**\n"
        "Shows the last signals generated:\n"
        "  • BUY 📈 = Price going up\n"
        "  • SELL 📉 = Price going down\n"
        "  • HOLD ⏸️ = No clear direction\n"
        "Usage: `/signals`\n\n"
        
        "**/analyze [SYMBOL]**\n"
        "Analyze a specific symbol RIGHT NOW\n"
        "Choose: BTC, ETH, or SOL\n"
        "Shows: current price, 5h/1h change, signal\n"
        "Usage: `/analyze BTC` or `/analyze ETH` or `/analyze SOL`\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*🎮 LIVE MONITORING*\n"
        "═══════════════════════════════════════════════\n\n"
        
        "**/live**\n"
        "Start continuous monitoring!\n"
        "Bot will send you updates every 30 seconds showing:\n"
        "  • Current price for BTC, ETH, SOL\n"
        "  • Price change (5h and 1h)\n"
        "  • Trading signal for each\n"
        "  • Current balance\n"
        "  • Daily P&L\n\n"
        "Great for watching the bot work in real-time!\n"
        "Usage: `/live`\n\n"
        
        "═══════════════════════════════════════════════\n"
        "*💡 TIPS*\n"
        "═══════════════════════════════════════════════\n\n"
        "🎯 Getting Started:\n"
        "  1. Type `/status` to see current state\n"
        "  2. Type `/live` to watch real-time signals\n"
        "  3. Type `/analyze BTC` to check specific symbol\n\n"
        
        "🔍 Understanding Signals:\n"
        "  📈 BUY = Price trending up, good entry\n"
        "  📉 SELL = Price trending down, exit signal\n"
        "  ⏸️ HOLD = Sideways/uncertain, wait\n\n"
        
        "🛡️ Risk Management:\n"
        "  • Bot stops trading if daily loss > 5%\n"
        "  • Max 3 consecutive losses before stop\n"
        "  • Use `/risk` to monitor limits\n\n"
        
        "⚙️ Testnet Mode:\n"
        "  • Using FAKE money (999 USDC)\n"
        "  • Safe for testing strategies\n"
        "  • Switch to mainnet when confident\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Bot status"""
    await risk_manager.load_state()
    bal = fetch_balance()
    risk = risk_manager.status()
    msg = format_status(bal, risk)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Quick balance check"""
    bal = fetch_balance()
    if "error" in bal:
        await update.message.reply_text(f"⚠️ {bal['error']}")
        return
    
    msg = (
        f"💰 *Account Balance*\n\n"
        f"Value: ${float(bal.get('account_value', 0)):,.2f}\n"
        f"Margin Used: ${float(bal.get('total_margin_used', 0)):,.2f}\n"
        f"Mode: {'🟢 Testnet' if cfg.HL_TESTNET else '🔴 Mainnet'}\n"
        f"Positions: {len(bal.get('positions', []))}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_risk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Risk details"""
    await risk_manager.load_state()
    risk = risk_manager.status()
    can = "✅ Trading enabled" if risk["can_trade"] else "❌ Trading blocked"
    
    msg = (
        f"🛡️ *Risk Status*\n\n"
        f"Daily P&L: ${risk['daily_pnl']:,.2f}\n"
        f"Daily Loss %: {risk['daily_dd_pct']:.2f}%\n"
        f"DD Limit: -{risk_manager.max_daily_dd_pct}%\n\n"
        f"Consecutive Losses: {risk['consecutive_losses']}/{risk_manager.max_consecutive_losses}\n"
        f"Circuit Breaker: {'🔴 ACTIVE!' if risk['circuit_breaker_active'] else '🟢 Off'}\n\n"
        f"Status: {can}"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_signals(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show last signals"""
    if not bot_state.last_signals:
        await update.message.reply_text("📭 No signals generated yet. Run /live to start analysis.")
        return
    
    lines = ["📊 *Last Signals*\n"]
    for symbol, data in bot_state.last_signals.items():
        signal = data["signal"]
        emoji = "📈" if "BUY" in signal else "📉" if "SELL" in signal else "⏸️"
        lines.append(f"{emoji} {symbol}: {signal}")
    
    msg = "\n".join(lines)
    await update.message.reply_text(msg, parse_mode="Markdown")

async def cmd_analyze(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Analyze specific symbol"""
    if not context.args or len(context.args) == 0:
        await update.message.reply_text("Usage: /analyze BTC (or ETH, SOL)")
        return
    
    symbol = context.args[0].upper()
    valid_symbols = ["BTC", "ETH", "SOL"]
    if symbol not in valid_symbols:
        await update.message.reply_text(f"Invalid symbol. Use: {', '.join(valid_symbols)}")
        return
    
    await update.message.reply_text(f"🔄 Analyzing {symbol}...")
    
    try:
        # Fetch candles
        candles_data = fetch_candles(symbol, "1h", 100)
        candles = candles_data if isinstance(candles_data, list) else candles_data.get("candles", [])
        
        if not candles or len(candles) < 20:
            await update.message.reply_text(f"⚠️ Insufficient data for {symbol}")
            return
        
        # Extract closes
        closes = []
        for c in candles:
            if isinstance(c, dict):
                closes.append(float(c.get("c", c.get("close", 0))))
            else:
                closes.append(float(c[4]))
        
        current_price = closes[-1]
        
        # Simple momentum (rising/falling)
        recent_change = (closes[-1] - closes[-5]) / closes[-5] * 100
        signal = "📈 BUY" if recent_change > 1 else "📉 SELL" if recent_change < -1 else "⏸️ HOLD"
        
        msg = (
            f"*{symbol} Analysis*\n\n"
            f"Price: ${current_price:,.2f}\n"
            f"5h Change: {recent_change:+.2f}%\n"
            f"Candles: {len(closes)}\n\n"
            f"Signal: {signal}\n"
            f"Status: Ready for trading"
        )
        
        bot_state.last_signals[symbol] = {
            "signal": signal,
            "timestamp": datetime.now().isoformat()
        }
        
        await update.message.reply_text(msg, parse_mode="Markdown")
        
    except Exception as e:
        logger.error(f"Analysis failed: {e}")
        await update.message.reply_text(f"❌ Analysis failed: {str(e)}")

async def cmd_live(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start live monitoring (30 min updates)"""
    await update.message.reply_text(
        "🟢 *Live Monitoring Started*\n\n"
        "Analyzing BTC, ETH, SOL every 30 minutes...\n"
        "You'll receive updates automatically.\n\n"
        "Use /stop to stop monitoring."
    )
    
    # Start monitoring in background
    context.application.create_task(
        monitor_signals(update.message.chat_id, context.application)
    )

async def monitor_signals(chat_id: int, app: Application):
    """Monitor signals and send updates"""
    symbols = ["BTC", "ETH", "SOL"]
    iteration = 0
    
    while True:
        try:
            iteration += 1
            timestamp = datetime.now().strftime("%H:%M:%S")
            
            # Analyze all symbols
            update_lines = [f"📊 *Signal Update #{iteration}* ({timestamp})\n"]
            
            for symbol in symbols:
                try:
                    candles_data = fetch_candles(symbol, "1h", 50)
                    candles = candles_data if isinstance(candles_data, list) else candles_data.get("candles", [])
                    
                    if candles and len(candles) >= 10:
                        closes = []
                        for c in candles:
                            if isinstance(c, dict):
                                closes.append(float(c.get("c", 0)))
                            else:
                                closes.append(float(c[4]))
                        
                        price = closes[-1]
                        change = (closes[-1] - closes[-3]) / closes[-3] * 100 if closes[-3] > 0 else 0
                        
                        signal = "📈" if change > 0.5 else "📉" if change < -0.5 else "⏸️"
                        update_lines.append(
                            f"{signal} {symbol}: ${price:,.2f} ({change:+.2f}%)"
                        )
                        
                        bot_state.last_signals[symbol] = {
                            "signal": signal,
                            "price": price,
                            "change": change,
                            "timestamp": timestamp
                        }
                except Exception as e:
                    logger.error(f"Analysis failed for {symbol}: {e}")
                    update_lines.append(f"⚠️ {symbol}: Error")
            
            # Send update
            try:
                await app.bot.send_message(
                    chat_id=chat_id,
                    text="\n".join(update_lines),
                    parse_mode="Markdown"
                )
            except TelegramError as e:
                logger.error(f"Telegram error: {e}")
                break
            
            # Wait 30 minutes (1800 seconds)
            # For testing, use shorter interval: 30 seconds
            await asyncio.sleep(30)  # Change to 1800 for production
            
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")
            await asyncio.sleep(5)

def run_bot():
    """Start Telegram bot"""
    if not cfg.TELEGRAM_BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = Application.builder().token(cfg.TELEGRAM_BOT_TOKEN).build()
    
    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("risk", cmd_risk))
    app.add_handler(CommandHandler("signals", cmd_signals))
    app.add_handler(CommandHandler("analyze", cmd_analyze))
    app.add_handler(CommandHandler("live", cmd_live))
    
    logger.info("🤖 Telegram Bot v2 Enhanced starting...")
    app.run_polling()

if __name__ == "__main__":
    run_bot()
