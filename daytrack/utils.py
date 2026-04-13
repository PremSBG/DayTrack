"""
Utilities Module
================
Shared validators and helper functions.
"""

import re
from datetime import datetime
from typing import List, Optional, Tuple

import pytz


# ── Content moderation ───────────────────────────────────────────────

# Common profanity / prohibited words (lowercase)
_BLOCKED_WORDS = {
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "pussy",
    "damn", "crap", "slut", "whore", "nigger", "faggot", "retard",
    "motherfucker", "bullshit", "ass", "wtf", "stfu", "lmao",
    "porn", "sex", "nude", "naked", "kill", "die", "suicide",
    "bomb", "terrorist", "drug", "cocaine", "heroin", "meth",
}


def check_content(text: str) -> Tuple[bool, str]:
    """Check if text contains prohibited content.

    Returns:
        (is_clean, message) — is_clean=True if text is OK,
        otherwise message explains the issue.
    """
    words = set(re.findall(r'\b\w+\b', text.lower()))
    bad = words & _BLOCKED_WORDS
    if bad:
        return False, "Please keep it friendly — no bad language here. 🙏 Let's focus on your day!"
    return True, ""


# Fixed schedule times (IST)
DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_MORNING_TIME = "07:00"
DEFAULT_EVENING_TIME = "23:00"


def validate_timezone(tz_str: str) -> bool:
    """Check if a string is a valid IANA timezone."""
    return tz_str in pytz.all_timezones


def validate_time_format(time_str: str) -> bool:
    """Check if a string matches HH:MM 24-hour format."""
    if not re.match(r"^\d{2}:\d{2}$", time_str):
        return False
    try:
        h, m = time_str.split(":")
        return 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except ValueError:
        return False


def today_str(tz_str: str = "Asia/Kolkata") -> str:
    """Return today's date as YYYY-MM-DD in the given timezone."""
    tz = pytz.timezone(tz_str)
    return datetime.now(tz).strftime("%Y-%m-%d")


def get_flow_reminders(db, user_id: int, flow_type: str) -> List[str]:
    """Get reminders for a flow. Returns custom if any, else defaults."""
    reminders = db.get_reminders(user_id, flow_type)
    if reminders:
        return [r["reminder_text"] for r in reminders]
    if flow_type == "morning":
        return ["💧 Hydrate", "🧘 Stretch a little", "🌅 Take a deep breath"]
    return ["🧴 Skincare", "💧 Drink water", "📖 Wind down"]


def format_reminders(reminders: List[str]) -> str:
    """Format a list of reminders into a nice message."""
    return "\n".join(f"  • {r}" for r in reminders)


def format_tasks_by_category(tasks: List[dict]) -> str:
    """Format tasks grouped by category for display."""
    by_cat = {}
    for t in tasks:
        cat = t.get("category", "other")
        by_cat.setdefault(cat, []).append(t["title"])
    lines = []
    emoji_map = {"work": "💼", "health": "🏃", "personal": "🏠", "learning": "📚", "other": "📌"}
    for cat, titles in by_cat.items():
        emoji = emoji_map.get(cat, "📌")
        lines.append(f"\n{emoji} {cat.title()}")
        for title in titles:
            lines.append(f"  • {title}")
    return "\n".join(lines)


def format_task_status_summary(tasks: List[dict]) -> str:
    """Format tasks with their statuses for evening review."""
    status_emoji = {"done": "✅", "partial": "🔶", "skipped": "⏭️", "pending": "⏳"}
    lines = []
    for t in tasks:
        emoji = status_emoji.get(t.get("status", "pending"), "⏳")
        lines.append(f"  {emoji} {t['title']}")
    return "\n".join(lines)


def calculate_day_score(tasks: List[dict]) -> str:
    """Calculate day score as 'done/total'."""
    total = len(tasks)
    if total == 0:
        return "0/0"
    done = sum(1 for t in tasks if t.get("status") == "done")
    return f"{done}/{total}"
