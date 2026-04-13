"""
DayTrack — Daily Companion Telegram Bot
Entry point.
"""

import logging

from dotenv import load_dotenv

load_dotenv()

from daytrack.ai_client import GroqAIClient
from daytrack.bot import create_app, trigger_evening_flow, trigger_morning_flow
from daytrack.config import Config
from daytrack.database import DatabaseManager
from daytrack.scheduler import init_scheduler, restore_all_schedules

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Initialize all components and start the bot."""
    # Validate config
    Config.validate()
    logger.info("Configuration validated")

    # Initialize database
    db = DatabaseManager(Config.SQLITE_DB_PATH)
    db.init_schema()
    logger.info(f"Database initialized at {Config.SQLITE_DB_PATH}")

    # Initialize AI client
    ai_client = GroqAIClient(
        api_key=Config.GROQ_API_KEY,
        model=Config.GROQ_MODEL,
        max_tokens=Config.GROQ_MAX_TOKENS,
        temperature=Config.GROQ_TEMPERATURE,
    )
    logger.info("Groq AI client initialized")

    # Initialize scheduler
    sched = init_scheduler()

    # Create bot application
    app = create_app(Config.TELEGRAM_BOT_TOKEN, db, ai_client)

    # Restore schedules for all active users
    count = restore_all_schedules(db, trigger_morning_flow, trigger_evening_flow)
    logger.info(f"Restored {count} user schedules")

    # Start scheduler
    sched.start()
    logger.info("Scheduler started")

    # Run the bot
    logger.info("Starting DayTrack bot...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
