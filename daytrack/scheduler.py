"""
Scheduler Module
================
Per-user scheduling for morning and evening flows using APScheduler.
"""

import logging
from typing import Optional

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger(__name__)

# Global scheduler instance — initialized in main
scheduler: Optional[AsyncIOScheduler] = None


def init_scheduler() -> AsyncIOScheduler:
    """Create and return the global scheduler."""
    global scheduler
    scheduler = AsyncIOScheduler()
    return scheduler


def schedule_user_flows(
    user_id: int,
    morning_time: str,
    evening_time: str,
    timezone: str,
    morning_callback,
    evening_callback,
) -> None:
    """Create morning and evening cron jobs for a user."""
    if scheduler is None:
        raise RuntimeError("Scheduler not initialized")

    m_hour, m_min = morning_time.split(":")
    e_hour, e_min = evening_time.split(":")

    scheduler.add_job(
        morning_callback,
        CronTrigger(hour=int(m_hour), minute=int(m_min), timezone=timezone),
        id=f"morning_{user_id}",
        args=[user_id],
        replace_existing=True,
    )
    scheduler.add_job(
        evening_callback,
        CronTrigger(hour=int(e_hour), minute=int(e_min), timezone=timezone),
        id=f"evening_{user_id}",
        args=[user_id],
        replace_existing=True,
    )
    logger.info(f"Scheduled flows for user {user_id}: morning={morning_time}, evening={evening_time}, tz={timezone}")


def reschedule_user_flows(
    user_id: int,
    morning_time: str,
    evening_time: str,
    timezone: str,
    morning_callback,
    evening_callback,
) -> None:
    """Remove old jobs and create new ones with updated settings."""
    if scheduler is None:
        raise RuntimeError("Scheduler not initialized")

    for job_id in [f"morning_{user_id}", f"evening_{user_id}"]:
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass

    schedule_user_flows(user_id, morning_time, evening_time, timezone,
                        morning_callback, evening_callback)


def restore_all_schedules(db, morning_callback, evening_callback) -> int:
    """On startup, re-schedule all active users. Returns count scheduled."""
    users = db.get_active_users()
    count = 0
    for user in users:
        try:
            schedule_user_flows(
                user["user_id"],
                user["morning_time"],
                user["evening_time"],
                user["timezone"],
                morning_callback,
                evening_callback,
            )
            count += 1
        except Exception as e:
            logger.error(f"Failed to schedule user {user['user_id']}: {e}")
    logger.info(f"Restored schedules for {count} users")
    return count
