"""
Configuration Module
====================
Centralized configuration management for the DayTrack Telegram Bot.
Loads environment variables and provides validation.

Environment Variables Required:
- TELEGRAM_BOT_TOKEN: Your Telegram bot token from @BotFather
- GROQ_API_KEY: Your Groq API key for AI features

Optional:
- SQLITE_DB_PATH: Path to SQLite database file (default: daytrack.db)
- GROQ_MODEL: Groq model name (default: llama-3.1-70b-versatile)
- GROQ_MAX_TOKENS: Max tokens for Groq responses (default: 1024)
- GROQ_TEMPERATURE: Temperature for Groq responses (default: 0.7)
"""

import os
from typing import Dict, Any


class Config:
    """Configuration class that loads and validates environment variables."""

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    GROQ_API_KEY: str = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL: str = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    GROQ_MAX_TOKENS: int = int(os.getenv("GROQ_MAX_TOKENS", "1024"))
    GROQ_TEMPERATURE: float = float(os.getenv("GROQ_TEMPERATURE", "0.7"))
    SQLITE_DB_PATH: str = os.getenv("SQLITE_DB_PATH", "daytrack.db")
    TURSO_DATABASE_URL: str = os.getenv("TURSO_DATABASE_URL", "")
    TURSO_AUTH_TOKEN: str = os.getenv("TURSO_AUTH_TOKEN", "")

    @classmethod
    def validate(cls) -> None:
        """Validate that all required configuration variables are set."""
        required = {
            "TELEGRAM_BOT_TOKEN": cls.TELEGRAM_BOT_TOKEN,
            "GROQ_API_KEY": cls.GROQ_API_KEY,
            "TURSO_DATABASE_URL": cls.TURSO_DATABASE_URL,
            "TURSO_AUTH_TOKEN": cls.TURSO_AUTH_TOKEN,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Please check your .env file or environment configuration."
            )

    @classmethod
    def to_dict(cls) -> Dict[str, Any]:
        """Return non-sensitive configuration as a dictionary."""
        return {
            "groq_model": cls.GROQ_MODEL,
            "groq_max_tokens": cls.GROQ_MAX_TOKENS,
            "groq_temperature": cls.GROQ_TEMPERATURE,
            "sqlite_db_path": cls.SQLITE_DB_PATH,
        }
