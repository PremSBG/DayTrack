"""
Bot Module
==========
Telegram bot handlers, conversation flows, and command routing for DayTrack.
"""

import json
import logging
from datetime import datetime, timedelta

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from daytrack.ai_client import ContentSafetyError, GroqAIClient
from daytrack.database import DatabaseManager
from daytrack.messages import (
    ask_custom_reminders, ask_morning_time, ask_evening_time, ask_timezone,
    evening_greeting, evening_memory_prompt, evening_memory_saved,
    evening_no_plan, evening_review_prompt, evening_score,
    fallback, goodnight, help_text, memory_recall, morning_greeting,
    morning_plan_prompt, morning_tasks_confirmation, morning_tasks_saved,
    no_memories, onboarding_complete, settings_menu, voice_not_supported,
    weekly_no_tasks, weekly_summary_header, welcome_back, welcome_new,
)
from daytrack.scheduler import (
    init_scheduler, reschedule_user_flows, restore_all_schedules,
    schedule_user_flows, scheduler,
)
from daytrack.utils import (
    DEFAULT_EVENING_TIME, DEFAULT_MORNING_TIME, DEFAULT_TIMEZONE,
    calculate_day_score, check_content, format_reminders,
    format_task_status_summary, format_tasks_by_category,
    get_flow_reminders, today_str, validate_time_format, validate_timezone,
)

logger = logging.getLogger(__name__)

# Global instances — set during startup
db: DatabaseManager = None  # type: ignore
ai: GroqAIClient = None  # type: ignore

# ── Conversation states ──────────────────────────────────────────────

# Onboarding
OB_NAME, OB_TIMEZONE, OB_REMINDERS = range(3)

# Morning flow
MF_PLAN, MF_CONFIRM = range(10, 12)

# Evening flow
EF_UPDATE, EF_MEMORY = range(20, 22)

# Settings
ST_CHOOSE, ST_VALUE = range(30, 32)
ST_REMINDER_ACTION, ST_REMINDER_ADD, ST_REMINDER_REMOVE = range(33, 36)


# ══════════════════════════════════════════════════════════════════════
# ONBOARDING FLOW
# ══════════════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start — begin onboarding or welcome back."""
    user = db.get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(welcome_back(user["first_name"]))
        return ConversationHandler.END
    await update.message.reply_text(welcome_new())
    return OB_NAME


async def ob_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Store name, ask timezone."""
    context.user_data["name"] = update.message.text.strip()
    await update.message.reply_text(f"Nice to meet you, {context.user_data['name']}! 😊\n\n{ask_timezone()}")
    return OB_TIMEZONE


async def ob_timezone(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Validate timezone, ask about custom reminders."""
    text = update.message.text.strip()
    if text.lower() == "skip":
        context.user_data["timezone"] = DEFAULT_TIMEZONE
    elif validate_timezone(text):
        context.user_data["timezone"] = text
    else:
        await update.message.reply_text(f"Hmm, '{text}' doesn't look like a valid timezone. Try again? (e.g., Asia/Kolkata)")
        return OB_TIMEZONE
    await update.message.reply_text(ask_custom_reminders())
    return OB_REMINDERS


async def ob_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle custom reminders or defaults, complete onboarding."""
    text = update.message.text.strip()
    user_id = update.effective_user.id
    ud = context.user_data

    # Create user with fixed times
    db.create_user(
        user_id=user_id,
        username=update.effective_user.username or "",
        first_name=ud["name"],
        timezone=ud.get("timezone", DEFAULT_TIMEZONE),
        morning_time=DEFAULT_MORNING_TIME,
        evening_time=DEFAULT_EVENING_TIME,
    )

    # Handle reminders
    if text.lower() in ("keep", "skip", "default", "defaults"):
        db.set_default_reminders(user_id)
    else:
        # Parse comma or newline separated custom reminders
        items = [r.strip() for r in text.replace("\n", ",").split(",") if r.strip()]
        if items:
            for item in items[:10]:
                db.add_reminder(user_id, "morning", item)
            db.set_default_reminders_evening_only(user_id) if hasattr(db, 'set_default_reminders_evening_only') else db.set_default_reminders(user_id)
        else:
            db.set_default_reminders(user_id)

    # Schedule flows
    user = db.get_user(user_id)
    schedule_user_flows(
        user_id, user["morning_time"], user["evening_time"], user["timezone"],
        trigger_morning_flow, trigger_evening_flow,
    )

    await update.message.reply_text(
        onboarding_complete(user["first_name"], user["timezone"])
    )
    return ConversationHandler.END


async def ob_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel onboarding."""
    await update.message.reply_text("No worries! Send /start whenever you're ready. 👋")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════
# MORNING FLOW
# ══════════════════════════════════════════════════════════════════════

async def trigger_morning_flow(user_id: int) -> None:
    """Scheduler callback — send morning greeting to user."""
    from daytrack.bot import _app
    user = db.get_user(user_id)
    if not user:
        return
    reminders = get_flow_reminders(db, user_id, "morning")
    text = (
        f"{morning_greeting(user['first_name'])}\n\n"
        f"Your morning reminders:\n{format_reminders(reminders)}\n"
        f"{morning_plan_prompt()}"
    )
    await _app.bot.send_message(chat_id=user_id, text=text)
    # Store conversation state in user_data via context isn't possible from scheduler,
    # so we track it in the database by creating a daily plan
    date = today_str(user["timezone"])
    existing = db.get_daily_plan(user_id, date)
    if not existing:
        db.create_daily_plan(user_id, date)


async def mf_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive plan text, parse with AI, show tasks."""
    user_id = update.effective_user.id
    plan_text = update.message.text.strip()

    # Content moderation
    is_clean, warning = check_content(plan_text)
    if not is_clean:
        await update.message.reply_text(warning)
        return MF_PLAN

    user = db.get_user(user_id)
    date = today_str(user["timezone"])

    try:
        tasks = ai.parse_morning_plan(plan_text)
        if not tasks:
            await update.message.reply_text("I couldn't find any tasks in that. Could you rephrase? 🤔")
            return MF_PLAN

        context.user_data["parsed_tasks"] = tasks
        context.user_data["raw_plan"] = plan_text
        formatted = format_tasks_by_category(tasks)
        await update.message.reply_text(morning_tasks_confirmation(formatted))
        return MF_CONFIRM
    except ContentSafetyError as e:
        await update.message.reply_text(str(e))
        return MF_PLAN
    except Exception as e:
        logger.error(f"Morning parse failed for user {user_id}: {e}")
        await update.message.reply_text(
            "Oops, I had trouble parsing that. Could you try rephrasing your plan? 🙏"
        )
        return MF_PLAN


async def mf_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Confirm or correct parsed tasks."""
    user_id = update.effective_user.id
    text = update.message.text.strip().lower()
    user = db.get_user(user_id)
    date = today_str(user["timezone"])

    if text in ("yes", "y", "looks good", "perfect", "confirm", "ok", "good", "yep", "yup"):
        tasks = context.user_data.get("parsed_tasks", [])
        raw = context.user_data.get("raw_plan", "")

        plan = db.get_daily_plan(user_id, date)
        if not plan:
            plan_id = db.create_daily_plan(user_id, date)
        else:
            plan_id = plan["id"]

        db.update_daily_plan(plan_id, raw_morning_input=raw,
                             morning_completed_at=datetime.utcnow().isoformat())
        db.create_tasks(plan_id, user_id, date, tasks)

        await update.message.reply_text(morning_tasks_saved())
        return ConversationHandler.END
    else:
        # User wants corrections — re-parse with the new input
        try:
            tasks = ai.parse_morning_plan(text)
            if tasks:
                context.user_data["parsed_tasks"] = tasks
                context.user_data["raw_plan"] = text
                formatted = format_tasks_by_category(tasks)
                await update.message.reply_text(morning_tasks_confirmation(formatted))
                return MF_CONFIRM
        except Exception:
            pass
        await update.message.reply_text("I'll try again — could you tell me your plan once more? 🤔")
        return MF_PLAN


# ══════════════════════════════════════════════════════════════════════
# EVENING FLOW
# ══════════════════════════════════════════════════════════════════════

async def trigger_evening_flow(user_id: int) -> None:
    """Scheduler callback — send evening greeting to user."""
    from daytrack.bot import _app
    user = db.get_user(user_id)
    if not user:
        return
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user_id, date)

    if plan and plan.get("morning_completed_at"):
        tasks = db.get_tasks_for_plan(plan["id"])
        formatted = format_tasks_by_category([dict(t) for t in tasks])
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_review_prompt(formatted)}"
    else:
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_no_plan()}"

    await _app.bot.send_message(chat_id=user_id, text=text)


async def ef_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Receive evening update, match against tasks."""
    user_id = update.effective_user.id
    update_text = update.message.text.strip()

    # Content moderation
    is_clean, warning = check_content(update_text)
    if not is_clean:
        await update.message.reply_text(warning)
        return EF_UPDATE

    user = db.get_user(user_id)
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user_id, date)

    if not plan or not plan.get("morning_completed_at"):
        # No morning plan — just save as reflection
        if not plan:
            plan_id = db.create_daily_plan(user_id, date)
        else:
            plan_id = plan["id"]
        db.update_daily_plan(plan_id, raw_evening_input=update_text)
        await update.message.reply_text(
            "Thanks for sharing! 💭\n" + evening_memory_prompt()
        )
        context.user_data["plan_id"] = plan_id
        return EF_MEMORY

    tasks = db.get_tasks_for_plan(plan["id"])
    task_dicts = [{"title": t["title"], "category": t["category"]} for t in tasks]

    try:
        matched = ai.match_evening_update(task_dicts, update_text)
        # Update task statuses
        for i, task in enumerate(tasks):
            if i < len(matched):
                status = matched[i].get("status", "skipped")
                db.update_task_status(task["id"], status)

        # Refresh tasks and calculate score
        updated_tasks = db.get_tasks_for_plan(plan["id"])
        score = calculate_day_score([dict(t) for t in updated_tasks])
        status_summary = format_task_status_summary([dict(t) for t in updated_tasks])

        db.update_daily_plan(plan["id"], raw_evening_input=update_text, day_score=score)

        await update.message.reply_text(evening_score(score, status_summary))
        await update.message.reply_text(evening_memory_prompt())
        context.user_data["plan_id"] = plan["id"]
        return EF_MEMORY

    except ContentSafetyError as e:
        await update.message.reply_text(str(e))
        return EF_UPDATE
    except Exception as e:
        logger.error(f"Evening match failed for user {user_id}: {e}")
        db.update_daily_plan(plan["id"], raw_evening_input=update_text)
        await update.message.reply_text(
            "I had trouble matching your update to tasks. No worries though!\n"
            + evening_memory_prompt()
        )
        context.user_data["plan_id"] = plan["id"]
        return EF_MEMORY


async def ef_memory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Capture memory or skip, send evening reminders and goodnight."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Content moderation
    is_clean, warning = check_content(text)
    if not is_clean:
        await update.message.reply_text(warning)
        return EF_MEMORY

    user = db.get_user(user_id)
    plan_id = context.user_data.get("plan_id")

    if text.lower() not in ("no", "skip", "nah", "nope", "pass", "none"):
        if plan_id:
            db.update_daily_plan(plan_id, moment=text)
        await update.message.reply_text(evening_memory_saved())

    # Mark evening complete
    if plan_id:
        db.update_daily_plan(plan_id, evening_completed_at=datetime.utcnow().isoformat())

    # Send evening reminders
    reminders = get_flow_reminders(db, user_id, "evening")
    reminder_text = f"\nEvening reminders:\n{format_reminders(reminders)}"
    await update.message.reply_text(reminder_text)
    await update.message.reply_text(goodnight(user["first_name"]))

    # Check if Sunday — trigger weekly summary
    tz = pytz.timezone(user["timezone"])
    now = datetime.now(tz)
    if now.weekday() == 6:  # Sunday
        await send_weekly_summary(user_id, update.message.reply_text)

    return ConversationHandler.END


async def send_weekly_summary(user_id: int, reply_func) -> None:
    """Generate and send weekly summary."""
    user = db.get_user(user_id)
    if not user:
        return

    tz = pytz.timezone(user["timezone"])
    now = datetime.now(tz)
    week_end = now.strftime("%Y-%m-%d")
    week_start = (now - timedelta(days=6)).strftime("%Y-%m-%d")

    tasks = db.get_tasks_for_week(user_id, week_start, week_end)
    if not tasks:
        await reply_func(weekly_no_tasks())
        return

    total = len(tasks)
    completed = sum(1 for t in tasks if t["status"] == "done")
    partial = sum(1 for t in tasks if t["status"] == "partial")
    skipped = sum(1 for t in tasks if t["status"] == "skipped")
    score_pct = round((completed / total) * 100, 1) if total > 0 else 0

    # Category breakdown
    cat_breakdown = {}
    for t in tasks:
        cat_breakdown[t["category"]] = cat_breakdown.get(t["category"], 0) + 1

    streak = db.calculate_streak(user_id)

    # AI insight
    week_data = {
        "total_tasks": total, "completed": completed, "partial": partial,
        "skipped": skipped, "score_percentage": score_pct,
        "category_breakdown": cat_breakdown, "streak_days": streak,
    }
    try:
        insight = ai.generate_weekly_insight(week_data)
    except Exception:
        insight = {"summary": "Great week! Keep it up.", "suggestions": "Stay consistent."}

    # Store summary
    summary_data = {
        "week_start": week_start, "week_end": week_end,
        "total_tasks": total, "completed_tasks": completed,
        "partial_tasks": partial, "skipped_tasks": skipped,
        "score_percentage": score_pct,
        "category_breakdown": json.dumps(cat_breakdown),
        "ai_summary": insight.get("summary", ""),
        "ai_suggestions": insight.get("suggestions", ""),
        "streak_days": streak,
    }
    db.create_weekly_summary(user_id, summary_data)

    # Format and send
    emoji_map = {"work": "💼", "health": "🏃", "personal": "🏠", "learning": "📚", "other": "📌"}
    cat_lines = "\n".join(f"  {emoji_map.get(c, '📌')} {c.title()}: {n}" for c, n in cat_breakdown.items())

    msg = (
        f"{weekly_summary_header()}\n\n"
        f"📈 Score: {score_pct}% ({completed}/{total} completed)\n"
        f"🔶 Partial: {partial} | ⏭️ Skipped: {skipped}\n\n"
        f"📊 Categories:\n{cat_lines}\n\n"
        f"🔥 Streak: {streak} days\n\n"
        f"💭 {insight.get('summary', '')}\n\n"
        f"💡 {insight.get('suggestions', '')}"
    )
    await reply_func(msg)


# ══════════════════════════════════════════════════════════════════════
# SETTINGS FLOW
# ══════════════════════════════════════════════════════════════════════

SETTINGS_OPTIONS = [
    [InlineKeyboardButton("👤 Name", callback_data="set_name")],
    [InlineKeyboardButton("🌍 Timezone", callback_data="set_timezone")],
    [InlineKeyboardButton("☀️ Morning Time", callback_data="set_morning")],
    [InlineKeyboardButton("🌙 Evening Time", callback_data="set_evening")],
    [InlineKeyboardButton("🌅 Morning Reminders", callback_data="set_mreminders")],
    [InlineKeyboardButton("🌙 Evening Reminders", callback_data="set_ereminders")],
    [InlineKeyboardButton("✅ Done", callback_data="set_done")],
]


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /settings — show current settings."""
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please run /start first to set up your profile! 😊")
        return ConversationHandler.END

    text = settings_menu(user["first_name"], user["timezone"], user["morning_time"], user["evening_time"])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(SETTINGS_OPTIONS))
    return ST_CHOOSE


async def st_choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle settings menu selection."""
    query = update.callback_query
    await query.answer()
    choice = query.data

    if choice == "set_done":
        await query.edit_message_text("Settings saved! 👍")
        return ConversationHandler.END
    elif choice == "set_name":
        context.user_data["setting"] = "first_name"
        await query.edit_message_text("What should I call you?")
        return ST_VALUE
    elif choice == "set_timezone":
        context.user_data["setting"] = "timezone"
        await query.edit_message_text(ask_timezone())
        return ST_VALUE
    elif choice == "set_morning":
        context.user_data["setting"] = "morning_time"
        await query.edit_message_text(ask_morning_time())
        return ST_VALUE
    elif choice == "set_evening":
        context.user_data["setting"] = "evening_time"
        await query.edit_message_text(ask_evening_time())
        return ST_VALUE
    elif choice in ("set_mreminders", "set_ereminders"):
        flow = "morning" if choice == "set_mreminders" else "evening"
        context.user_data["reminder_flow"] = flow
        return await show_reminder_menu(query, update.effective_user.id, flow)

    return ST_CHOOSE


async def st_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle settings value input."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    setting = context.user_data.get("setting")

    if setting == "timezone":
        if text.lower() == "skip":
            pass
        elif not validate_timezone(text):
            await update.message.reply_text(f"'{text}' isn't a valid timezone. Try again?")
            return ST_VALUE
        else:
            db.update_user_setting(user_id, "timezone", text)
    elif setting in ("morning_time", "evening_time"):
        if text.lower() == "skip":
            pass
        elif not validate_time_format(text):
            await update.message.reply_text("Please use HH:MM format (24-hour), like 07:00")
            return ST_VALUE
        else:
            db.update_user_setting(user_id, setting, text)
    elif setting == "first_name":
        db.update_user_setting(user_id, "first_name", text)
    else:
        await update.message.reply_text("Something went wrong. Try /settings again.")
        return ConversationHandler.END

    # Reschedule if time/timezone changed
    if setting in ("morning_time", "evening_time", "timezone"):
        user = db.get_user(user_id)
        reschedule_user_flows(
            user_id, user["morning_time"], user["evening_time"], user["timezone"],
            trigger_morning_flow, trigger_evening_flow,
        )

    await update.message.reply_text("Updated! ✅", reply_markup=InlineKeyboardMarkup(SETTINGS_OPTIONS))
    return ST_CHOOSE


async def show_reminder_menu(query, user_id: int, flow: str) -> int:
    """Show current reminders with add/remove/done options."""
    reminders = db.get_reminders(user_id, flow)
    if reminders:
        lines = [f"  {i+1}. {r['reminder_text']}" for i, r in enumerate(reminders)]
        text = f"Your {flow} reminders:\n" + "\n".join(lines)
    else:
        text = f"No custom {flow} reminders set (using defaults)."

    keyboard = [
        [InlineKeyboardButton("➕ Add", callback_data="rem_add"),
         InlineKeyboardButton("➖ Remove", callback_data="rem_remove"),
         InlineKeyboardButton("✅ Done", callback_data="rem_done")],
    ]
    await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    return ST_REMINDER_ACTION


async def st_reminder_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle reminder add/remove/done."""
    query = update.callback_query
    await query.answer()
    choice = query.data
    flow = context.user_data.get("reminder_flow", "morning")

    if choice == "rem_done":
        await query.edit_message_text("Reminders saved! ✅", reply_markup=InlineKeyboardMarkup(SETTINGS_OPTIONS))
        return ST_CHOOSE
    elif choice == "rem_add":
        count = db.get_reminder_count(update.effective_user.id, flow)
        if count >= 10:
            await query.edit_message_text(
                f"You've hit the max of 10 {flow} reminders. Remove one first!",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="rem_done")]]),
            )
            return ST_REMINDER_ACTION
        await query.edit_message_text(f"Type your new {flow} reminder (max 100 chars):")
        return ST_REMINDER_ADD
    elif choice == "rem_remove":
        reminders = db.get_reminders(update.effective_user.id, flow)
        if not reminders:
            await query.edit_message_text("No reminders to remove!")
            return await show_reminder_menu(query, update.effective_user.id, flow)
        keyboard = [[InlineKeyboardButton(f"{i+1}. {r['reminder_text'][:30]}", callback_data=f"remid_{r['id']}")]
                     for i, r in enumerate(reminders)]
        keyboard.append([InlineKeyboardButton("⬅️ Back", callback_data="rem_done")])
        await query.edit_message_text("Which reminder to remove?", reply_markup=InlineKeyboardMarkup(keyboard))
        return ST_REMINDER_REMOVE

    return ST_REMINDER_ACTION


async def st_reminder_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Add a new reminder."""
    text = update.message.text.strip()[:100]
    user_id = update.effective_user.id
    flow = context.user_data.get("reminder_flow", "morning")

    if db.add_reminder(user_id, flow, text):
        await update.message.reply_text(f"Added: {text} ✅")
    else:
        await update.message.reply_text("Couldn't add — you might be at the limit.")

    # Show menu again
    reminders = db.get_reminders(user_id, flow)
    lines = [f"  {i+1}. {r['reminder_text']}" for i, r in enumerate(reminders)]
    msg = f"Your {flow} reminders:\n" + "\n".join(lines)
    keyboard = [
        [InlineKeyboardButton("➕ Add", callback_data="rem_add"),
         InlineKeyboardButton("➖ Remove", callback_data="rem_remove"),
         InlineKeyboardButton("✅ Done", callback_data="rem_done")],
    ]
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    return ST_REMINDER_ACTION


async def st_reminder_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Remove a reminder by callback."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "rem_done":
        await query.edit_message_text("Reminders saved! ✅", reply_markup=InlineKeyboardMarkup(SETTINGS_OPTIONS))
        return ST_CHOOSE

    if data.startswith("remid_"):
        reminder_id = int(data.split("_")[1])
        db.remove_reminder(reminder_id, update.effective_user.id)

    flow = context.user_data.get("reminder_flow", "morning")
    return await show_reminder_menu(query, update.effective_user.id, flow)


# ══════════════════════════════════════════════════════════════════════
# STANDALONE COMMANDS
# ══════════════════════════════════════════════════════════════════════

async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /today — show today's plan and task statuses."""
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please run /start first! 😊")
        return
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user.get("user_id"), date)
    if not plan:
        await update.message.reply_text("No plan set for today yet. I'll ask you during your morning check-in! ☀️")
        return
    tasks = db.get_tasks_for_plan(plan["id"])
    if not tasks:
        await update.message.reply_text("You have a plan started but no tasks parsed yet. Hang tight! 📝")
        return
    formatted = format_tasks_by_category([dict(t) for t in tasks])
    status = format_task_status_summary([dict(t) for t in tasks])
    score = calculate_day_score([dict(t) for t in tasks])
    await update.message.reply_text(f"📋 Today's plan ({date}):\n{formatted}\n\n📊 Status:\n{status}\n\n🎯 Score: {score}")


async def memories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /memories — show a random past memory."""
    user_id = update.effective_user.id
    memory = db.get_random_memory(user_id)
    if memory:
        await update.message.reply_text(memory_recall(memory["moment"], memory["plan_date"]))
    else:
        await update.message.reply_text(no_memories())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /help — list available commands."""
    await update.message.reply_text(help_text())


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle voice messages — politely decline."""
    await update.message.reply_text(voice_not_supported())


async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle unrecognized messages outside conversations."""
    await update.message.reply_text(fallback())


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors."""
    logger.error(f"Exception while handling update: {context.error}", exc_info=context.error)


# ══════════════════════════════════════════════════════════════════════
# APPLICATION SETUP
# ══════════════════════════════════════════════════════════════════════

# Global app reference for scheduler callbacks
_app: Application = None  # type: ignore


def create_app(token: str, database: DatabaseManager, ai_client: GroqAIClient) -> Application:
    """Build and configure the Telegram bot application."""
    global db, ai, _app

    db = database
    ai = ai_client

    app = Application.builder().token(token).build()
    _app = app

    # Onboarding conversation (simplified — fixed times)
    onboarding_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={
            OB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_name)],
            OB_TIMEZONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_timezone)],
            OB_REMINDERS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_reminders)],
        },
        fallbacks=[CommandHandler("cancel", ob_cancel)],
        name="onboarding",
    )

    # Morning flow conversation
    morning_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, mf_plan)],
        states={
            MF_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, mf_plan)],
            MF_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, mf_confirm)],
        },
        fallbacks=[CommandHandler("cancel", ob_cancel)],
        name="morning_flow",
    )

    # Evening flow conversation
    evening_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, ef_update)],
        states={
            EF_UPDATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ef_update)],
            EF_MEMORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, ef_memory)],
        },
        fallbacks=[CommandHandler("cancel", ob_cancel)],
        name="evening_flow",
    )

    # Settings conversation
    settings_handler = ConversationHandler(
        entry_points=[CommandHandler("settings", settings_command)],
        states={
            ST_CHOOSE: [CallbackQueryHandler(st_choose)],
            ST_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, st_value)],
            ST_REMINDER_ACTION: [CallbackQueryHandler(st_reminder_action)],
            ST_REMINDER_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, st_reminder_add)],
            ST_REMINDER_REMOVE: [CallbackQueryHandler(st_reminder_remove)],
        },
        fallbacks=[CommandHandler("cancel", ob_cancel)],
        name="settings",
    )

    # Register handlers (order matters)
    app.add_handler(onboarding_handler)
    app.add_handler(settings_handler)
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("memories", memories_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE, voice_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    app.add_error_handler(error_handler)

    return app
