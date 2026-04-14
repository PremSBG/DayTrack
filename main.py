"""
DayTrack — Daily Companion Telegram Bot
Entry point with proper HTTP health server for Render.
"""

import asyncio
import logging
import os
from aiohttp import web

from dotenv import load_dotenv
load_dotenv()

from daytrack.ai_client import GroqAIClient
from daytrack.bot import create_app, trigger_evening_flow, trigger_morning_flow
from daytrack.config import Config
from daytrack.database import DatabaseManager
from daytrack.scheduler import init_scheduler, restore_all_schedules

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)


async def health_handler(request):
    """Health check endpoint for Render / cron pings."""
    return web.Response(text="OK")


async def run_health_server():
    """Run aiohttp health server on $PORT."""
    port = int(os.getenv("PORT", "8080"))
    app = web.Application()
    app.router.add_get("/", health_handler)
    app.router.add_get("/health", health_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logger.info(f"Health server on port {port}")


def main() -> None:
    Config.validate()
    logger.info("Config validated")

    db = DatabaseManager(Config.SQLITE_DB_PATH)
    db.init_schema()
    logger.info("Database ready")

    ai_client = GroqAIClient(
        api_key=Config.GROQ_API_KEY, model=Config.GROQ_MODEL,
        max_tokens=Config.GROQ_MAX_TOKENS, temperature=Config.GROQ_TEMPERATURE)
    logger.info("AI client ready")

    sched = init_scheduler()
    app = create_app(Config.TELEGRAM_BOT_TOKEN, db, ai_client)

    count = restore_all_schedules(db, trigger_morning_flow, trigger_evening_flow)
    logger.info(f"Restored {count} schedules")

    sched.start()
    logger.info("Scheduler started")

    # Start health server in the same event loop as the bot
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(run_health_server())

    logger.info("Starting DayTrack bot...")
    app.run_polling(drop_pending_updates=False)


if __name__ == "__main__":
    main()
