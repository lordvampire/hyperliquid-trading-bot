"""Configuration — loads from .env, never hardcodes secrets."""

import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    # Hyperliquid
    HL_SECRET_KEY: str = os.getenv("HL_SECRET_KEY", "")
    HL_TESTNET: bool = os.getenv("HL_TESTNET", "true").lower() == "true"
    HL_WALLET_ADDRESS: str = os.getenv("HL_WALLET_ADDRESS", "")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_CHAT_ID: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Risk
    RISK_MAX_DAILY_DD_PCT: float = float(os.getenv("RISK_MAX_DAILY_DD_PCT", "5.0"))
    RISK_MAX_CONSECUTIVE_LOSSES: int = int(os.getenv("RISK_MAX_CONSECUTIVE_LOSSES", "3"))
    RISK_DEFAULT_SIZE_PCT: float = float(os.getenv("RISK_DEFAULT_SIZE_PCT", "2.0"))

    # Server
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))

    # Database
    DB_PATH: str = os.getenv("DB_PATH", "trading_bot.db")

    @classmethod
    def validate(cls) -> list[str]:
        """Return list of missing required config keys."""
        issues = []
        if not cls.HL_SECRET_KEY:
            issues.append("HL_SECRET_KEY not set")
        if not cls.HL_WALLET_ADDRESS:
            issues.append("HL_WALLET_ADDRESS not set")
        return issues


cfg = Config()
