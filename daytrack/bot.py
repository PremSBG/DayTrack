"""
Bot Module — Telegram handlers with button-based UI for DayTrack.
"""

import json
import logging
from datetime import datetime, timedelta

import pytz
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ConversationHandler,
    ContextTypes, MessageHandler, filters,
)

from daytrack.ai_client import ContentSafetyError, GroqAIClient
from daytrack.database import DatabaseManager
from daytrack.messages import *
from daytrack.scheduler import reschedule_user_flows, schedule_user_flows
from daytrack.utils import (
    DEFAULT_EVENING_TIME, DEFAULT_MORNING_TIME, DEFAULT_TIMEZONE,
    calculate_day_score, check_content, format_reminders,
    format_task_status_summary, format_tasks_by_category,
    get_flow_reminders, today_str, validate_time_format, validate_timezone,
)

logger = logging.getLogger(__name__)

db: DatabaseManager = None  # type: ignore
ai: GroqAIClient = None  # type: ignore

# Conversation states
OB_NAME = 0
MF_PLAN, MF_CONFIRM = 10, 11
EF_UPDATE, EF_MEMORY = 20, 21
ST_CHOOSE, ST_VALUE = 30, 31
ST_REM_ACTION, ST_REM_ADD, ST_REM_REMOVE = 33, 34, 35


# ── Shared UI ────────────────────────────────────────────────────────

def main_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("☀️ Morning", callback_data="menu_morning"),
         InlineKeyboardButton("🌙 Evening", callback_data="menu_evening")],
        [InlineKeyboardButton("📋 Today", callback_data="menu_today"),
         InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings")],
        [InlineKeyboardButton("💭 Memories", callback_data="menu_memories"),
         InlineKeyboardButton("❓ Help", callback_data="menu_help")],
    ])


def back_menu_keyboard():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🏠 Main Menu", callback_data="menu_main")]])


async def cancel_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel any conversation and show main menu."""
    user = db.get_user(update.effective_user.id)
    if user:
        await update.message.reply_text("Cancelled! 👍", reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("Cancelled! Send /start to begin.")
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════
# ONBOARDING
# ══════════════════════════════════════════════════════════════════════

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = db.get_user(update.effective_user.id)
    if user:
        await update.message.reply_text(welcome_back(user["first_name"]), reply_markup=main_menu_keyboard())
        return ConversationHandler.END
    await update.message.reply_text(welcome_new())
    return OB_NAME


async def ob_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    name = update.message.text.strip()
    user_id = update.effective_user.id

    is_clean, warning = check_content(name)
    if not is_clean:
        await update.message.reply_text(warning)
        return OB_NAME

    db.create_user(user_id, update.effective_user.username or "", name,
                   DEFAULT_TIMEZONE, DEFAULT_MORNING_TIME, DEFAULT_EVENING_TIME)
    db.set_default_reminders(user_id)

    user = db.get_user(user_id)
    schedule_user_flows(user_id, user["morning_time"], user["evening_time"],
                        user["timezone"], trigger_morning_flow, trigger_evening_flow)

    await update.message.reply_text(onboarding_complete(name), reply_markup=main_menu_keyboard())
    return ConversationHandler.END


async def ob_command_fallback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """If user sends a command during onboarding, auto-complete with defaults."""
    user_id = update.effective_user.id
    if db.get_user(user_id):
        await update.message.reply_text("You're set up! 😊", reply_markup=main_menu_keyboard())
        return ConversationHandler.END

    name = update.effective_user.first_name or "Friend"
    db.create_user(user_id, update.effective_user.username or "", name,
                   DEFAULT_TIMEZONE, DEFAULT_MORNING_TIME, DEFAULT_EVENING_TIME)
    db.set_default_reminders(user_id)
    user = db.get_user(user_id)
    schedule_user_flows(user_id, user["morning_time"], user["evening_time"],
                        user["timezone"], trigger_morning_flow, trigger_evening_flow)
    await update.message.reply_text(
        f"Set you up as {name} with defaults! 🎉\nCustomize with ⚙️ Settings.",
        reply_markup=main_menu_keyboard())
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════
# MAIN MENU CALLBACK
# ══════════════════════════════════════════════════════════════════════

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    user = db.get_user(user_id)

    if not user:
        await query.edit_message_text("Please tap /start first! 😊")
        return

    if data == "menu_main":
        await query.edit_message_text(welcome_back(user["first_name"]), reply_markup=main_menu_keyboard())
    elif data == "menu_morning":
        await handle_morning_entry(query, user)
    elif data == "menu_evening":
        await handle_evening_entry(query, user)
    elif data == "menu_today":
        await handle_today(query, user)
    elif data == "menu_settings":
        await handle_settings_display(query, user)
    elif data == "menu_memories":
        await handle_memories(query, user_id)
    elif data == "menu_help":
        await query.edit_message_text(help_text(), reply_markup=back_menu_keyboard())


# ══════════════════════════════════════════════════════════════════════
# MORNING FLOW
# ══════════════════════════════════════════════════════════════════════

async def handle_morning_entry(query, user):
    """Show morning info from menu button. User must use /morning to enter the flow."""
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user["user_id"], date)
    if plan and plan.get("morning_completed_at"):
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 See Plan", callback_data="menu_today")],
            [InlineKeyboardButton("🏠 Menu", callback_data="menu_main")],
        ])
        await query.edit_message_text(morning_already_done(), reply_markup=kb)
        return

    reminders = get_flow_reminders(db, user["user_id"], "morning")
    text = (f"{morning_greeting(user['first_name'])}\n\nReminders:\n{format_reminders(reminders)}\n{morning_plan_prompt()}\n\n"
            "👉 Type /morning to start planning, or just type your tasks below!")
    await query.edit_message_text(text)


async def morning_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first! 😊")
        return ConversationHandler.END

    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user["user_id"], date)
    if plan and plan.get("morning_completed_at"):
        await update.message.reply_text(morning_already_done(), reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 See Plan", callback_data="menu_today"),
             InlineKeyboardButton("🏠 Menu", callback_data="menu_main")]]))
        return ConversationHandler.END

    reminders = get_flow_reminders(db, user["user_id"], "morning")
    text = f"{morning_greeting(user['first_name'])}\n\nReminders:\n{format_reminders(reminders)}\n{morning_plan_prompt()}"
    await update.message.reply_text(text)
    if not db.get_daily_plan(user["user_id"], date):
        db.create_daily_plan(user["user_id"], date)
    return MF_PLAN


async def mf_plan(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    plan_text = update.message.text.strip()

    is_clean, warning = check_content(plan_text)
    if not is_clean:
        await update.message.reply_text(warning)
        return MF_PLAN

    user = db.get_user(user_id)
    try:
        tasks = ai.parse_morning_plan(plan_text)
        if not tasks:
            await update.message.reply_text("Couldn't find tasks. Try again? 🤔")
            return MF_PLAN
        context.user_data["parsed_tasks"] = tasks
        context.user_data["raw_plan"] = plan_text
        formatted = format_tasks_by_category(tasks)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ Looks good", callback_data="mf_confirm"),
             InlineKeyboardButton("🔄 Redo", callback_data="mf_redo")],
        ])
        await update.message.reply_text(morning_tasks_confirmation(formatted), reply_markup=kb)
        return MF_CONFIRM
    except ContentSafetyError as e:
        await update.message.reply_text(str(e))
        return MF_PLAN
    except Exception as e:
        logger.error(f"Morning parse failed: {e}")
        await update.message.reply_text("Had trouble parsing. Try rephrasing? 🙏")
        return MF_PLAN


async def mf_confirm_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id

    if query.data == "mf_redo":
        await query.edit_message_text("No problem! Tell me your plan again 📝")
        return MF_PLAN

    # Confirm
    user = db.get_user(user_id)
    date = today_str(user["timezone"])
    tasks = context.user_data.get("parsed_tasks", [])
    raw = context.user_data.get("raw_plan", "")

    plan = db.get_daily_plan(user_id, date)
    if not plan:
        plan_id = db.create_daily_plan(user_id, date)
    else:
        plan_id = plan["id"]

    db.update_daily_plan(plan_id, raw_morning_input=raw, morning_completed_at=datetime.utcnow().isoformat())
    db.create_tasks(plan_id, user_id, date, tasks)

    await query.edit_message_text(morning_tasks_saved(), reply_markup=back_menu_keyboard())
    return ConversationHandler.END


async def mf_confirm_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """If user types text instead of clicking button during confirm."""
    text = update.message.text.strip().lower()
    if text in ("yes", "y", "looks good", "ok", "good", "confirm", "yep", "yup"):
        # Simulate confirm
        user_id = update.effective_user.id
        user = db.get_user(user_id)
        date = today_str(user["timezone"])
        tasks = context.user_data.get("parsed_tasks", [])
        raw = context.user_data.get("raw_plan", "")
        plan = db.get_daily_plan(user_id, date)
        plan_id = plan["id"] if plan else db.create_daily_plan(user_id, date)
        db.update_daily_plan(plan_id, raw_morning_input=raw, morning_completed_at=datetime.utcnow().isoformat())
        db.create_tasks(plan_id, user_id, date, tasks)
        await update.message.reply_text(morning_tasks_saved(), reply_markup=back_menu_keyboard())
        return ConversationHandler.END
    else:
        # Re-parse
        return await mf_plan(update, context)


# ══════════════════════════════════════════════════════════════════════
# EVENING FLOW
# ══════════════════════════════════════════════════════════════════════

async def handle_evening_entry(query, user):
    """Show evening info from menu button. User must use /evening to enter the flow."""
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user["user_id"], date)
    if plan and plan.get("evening_completed_at"):
        await query.edit_message_text(evening_already_done(), reply_markup=back_menu_keyboard())
        return

    if plan and plan.get("morning_completed_at"):
        tasks = db.get_tasks_for_plan(plan["id"])
        formatted = format_tasks_by_category(tasks)
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_review_prompt(formatted)}\n\n👉 Type /evening to start your review!"
    else:
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_no_plan()}\n\n👉 Type /evening to share your reflection!"
    await query.edit_message_text(text)


async def evening_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first! 😊")
        return ConversationHandler.END

    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user["user_id"], date)
    if plan and plan.get("evening_completed_at"):
        await update.message.reply_text(evening_already_done(), reply_markup=back_menu_keyboard())
        return ConversationHandler.END

    if plan and plan.get("morning_completed_at"):
        tasks = db.get_tasks_for_plan(plan["id"])
        formatted = format_tasks_by_category(tasks)
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_review_prompt(formatted)}"
    else:
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_no_plan()}"
    await update.message.reply_text(text)
    return EF_UPDATE


async def ef_update(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    update_text = update.message.text.strip()

    is_clean, warning = check_content(update_text)
    if not is_clean:
        await update.message.reply_text(warning)
        return EF_UPDATE

    user = db.get_user(user_id)
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user_id, date)

    if not plan or not plan.get("morning_completed_at"):
        if not plan:
            plan_id = db.create_daily_plan(user_id, date)
        else:
            plan_id = plan["id"]
        db.update_daily_plan(plan_id, raw_evening_input=update_text)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💭 Save memory", callback_data="ef_memory_yes"),
             InlineKeyboardButton("⏭️ Skip", callback_data="ef_memory_skip")],
        ])
        await update.message.reply_text("Thanks for sharing! 💭\n\n" + evening_memory_prompt(), reply_markup=kb)
        context.user_data["plan_id"] = plan_id
        return EF_MEMORY

    tasks = db.get_tasks_for_plan(plan["id"])
    task_dicts = [{"title": t["title"], "category": t["category"]} for t in tasks]

    try:
        matched = ai.match_evening_update(task_dicts, update_text)
        for i, task in enumerate(tasks):
            if i < len(matched):
                db.update_task_status(task["id"], matched[i].get("status", "skipped"))

        updated = db.get_tasks_for_plan(plan["id"])
        score = calculate_day_score(updated)
        summary = format_task_status_summary(updated)
        db.update_daily_plan(plan["id"], raw_evening_input=update_text, day_score=score)

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💭 Save memory", callback_data="ef_memory_yes"),
             InlineKeyboardButton("⏭️ Skip", callback_data="ef_memory_skip")],
        ])
        await update.message.reply_text(evening_score(score, summary))
        await update.message.reply_text(evening_memory_prompt(), reply_markup=kb)
        context.user_data["plan_id"] = plan["id"]
        return EF_MEMORY

    except ContentSafetyError as e:
        await update.message.reply_text(str(e))
        return EF_UPDATE
    except Exception as e:
        logger.error(f"Evening match failed: {e}")
        db.update_daily_plan(plan["id"], raw_evening_input=update_text)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("💭 Save memory", callback_data="ef_memory_yes"),
             InlineKeyboardButton("⏭️ Skip", callback_data="ef_memory_skip")],
        ])
        await update.message.reply_text("Had trouble matching tasks. No worries!\n\n" + evening_memory_prompt(), reply_markup=kb)
        context.user_data["plan_id"] = plan["id"]
        return EF_MEMORY


async def ef_memory_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    user_id = update.effective_user.id
    user = db.get_user(user_id)
    plan_id = context.user_data.get("plan_id")

    if query.data == "ef_memory_skip":
        if plan_id:
            db.update_daily_plan(plan_id, evening_completed_at=datetime.utcnow().isoformat())
        reminders = get_flow_reminders(db, user_id, "evening")
        text = f"Evening reminders:\n{format_reminders(reminders)}\n\n{goodnight(user['first_name'])}"
        await query.edit_message_text(text, reply_markup=back_menu_keyboard())

        # Weekly summary on Sunday
        tz = pytz.timezone(user["timezone"])
        if datetime.now(tz).weekday() == 6:
            await send_weekly_summary(user_id, query.message.reply_text)
        return ConversationHandler.END

    elif query.data == "ef_memory_yes":
        await query.edit_message_text("Type your memory or thought 💭")
        return EF_MEMORY

    return EF_MEMORY


async def ef_memory_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    is_clean, warning = check_content(text)
    if not is_clean:
        await update.message.reply_text(warning)
        return EF_MEMORY

    user = db.get_user(user_id)
    plan_id = context.user_data.get("plan_id")
    if plan_id:
        db.update_daily_plan(plan_id, moment=text, evening_completed_at=datetime.utcnow().isoformat())

    reminders = get_flow_reminders(db, user_id, "evening")
    await update.message.reply_text(evening_memory_saved())
    msg = f"Evening reminders:\n{format_reminders(reminders)}\n\n{goodnight(user['first_name'])}"
    await update.message.reply_text(msg, reply_markup=back_menu_keyboard())

    tz = pytz.timezone(user["timezone"])
    if datetime.now(tz).weekday() == 6:
        await send_weekly_summary(user_id, update.message.reply_text)
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════
# SETTINGS
# ══════════════════════════════════════════════════════════════════════

SETTINGS_KB = InlineKeyboardMarkup([
    [InlineKeyboardButton("👤 Name", callback_data="set_name"),
     InlineKeyboardButton("☀️ Morning Time", callback_data="set_morning")],
    [InlineKeyboardButton("🌙 Evening Time", callback_data="set_evening")],
    [InlineKeyboardButton("🌅 Morning Reminders", callback_data="set_mrem"),
     InlineKeyboardButton("🌙 Evening Reminders", callback_data="set_erem")],
    [InlineKeyboardButton("🏠 Back", callback_data="menu_main")],
])


async def handle_settings_display(query, user):
    text = settings_display(user["first_name"], user["timezone"], user["morning_time"], user["evening_time"])
    await query.edit_message_text(text, reply_markup=SETTINGS_KB)


async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        user = db.get_user(update.effective_user.id)
        if not user:
            await update.message.reply_text("Please /start first! 😊")
            return ConversationHandler.END
        text = settings_display(user["first_name"], user["timezone"], user["morning_time"], user["evening_time"])
        await update.message.reply_text(text, reply_markup=SETTINGS_KB)
        return ST_CHOOSE
    except Exception as e:
        logger.error(f"Error in settings_command: {e}")
        await update.message.reply_text("Sorry, there was an error. Please try again.")
        return ConversationHandler.END


async def st_choose(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    choice = query.data

    try:
        if choice == "menu_main":
            user = db.get_user(update.effective_user.id)
            await query.edit_message_text(welcome_back(user["first_name"]), reply_markup=main_menu_keyboard())
            return ConversationHandler.END
        elif choice == "set_name":
            context.user_data["setting"] = "first_name"
            await query.edit_message_text("What should I call you?")
            return ST_VALUE
        elif choice == "set_morning":
            context.user_data["setting"] = "morning_time"
            await query.edit_message_text("Morning time? (HH:MM, 24hr)\nExample: 07:00")
            return ST_VALUE
        elif choice == "set_evening":
            context.user_data["setting"] = "evening_time"
            await query.edit_message_text("Evening time? (HH:MM, 24hr)\nExample: 23:00")
            return ST_VALUE
        elif choice in ("set_mrem", "set_erem"):
            flow = "morning" if choice == "set_mrem" else "evening"
            context.user_data["rem_flow"] = flow
            return await show_rem_menu(query, update.effective_user.id, flow)

        return ST_CHOOSE
    except Exception as e:
        logger.error(f"Error in st_choose: {e}")
        await query.edit_message_text("Sorry, there was an error. Please try /settings again.")
        return ConversationHandler.END


async def st_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    setting = context.user_data.get("setting")

    if setting in ("morning_time", "evening_time"):
        if not validate_time_format(text):
            await update.message.reply_text("Use HH:MM format (24hr), like 07:00")
            return ST_VALUE
    elif setting == "first_name":
        is_clean, warning = check_content(text)
        if not is_clean:
            await update.message.reply_text(warning)
            return ST_VALUE

    try:
        if setting in ("morning_time", "evening_time"):
            db.update_user_setting(user_id, setting, text)
            user = db.get_user(user_id)
            reschedule_user_flows(user_id, user["morning_time"], user["evening_time"],
                                  user["timezone"], trigger_morning_flow, trigger_evening_flow)
        elif setting == "first_name":
            db.update_user_setting(user_id, "first_name", text)

        user = db.get_user(user_id)
        await update.message.reply_text(
            f"Updated! ✅\n\n{settings_display(user['first_name'], user['timezone'], user['morning_time'], user['evening_time'])}",
            reply_markup=SETTINGS_KB)
        return ST_CHOOSE
    except Exception as e:
        logger.error(f"Error updating setting: {e}")
        await update.message.reply_text("Sorry, there was an error updating your settings. Please try again.")
        return ST_CHOOSE


async def show_rem_menu(query, user_id, flow):
    try:
        reminders = db.get_reminders(user_id, flow)
        if reminders:
            lines = [f"  {i+1}. {r['reminder_text']}" for i, r in enumerate(reminders)]
            text = f"Your {flow} reminders:\n" + "\n".join(lines)
        else:
            text = f"No {flow} reminders (using defaults)."
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("➕ Add", callback_data="rem_add"),
             InlineKeyboardButton("➖ Remove", callback_data="rem_remove")],
            [InlineKeyboardButton("✅ Done", callback_data="rem_done")],
        ])
        await query.edit_message_text(text, reply_markup=kb)
        return ST_REM_ACTION
    except Exception as e:
        logger.error(f"Error in show_rem_menu: {e}")
        await query.edit_message_text("Sorry, there was an error. Please try /settings again.")
        return ConversationHandler.END


async def st_rem_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    flow = context.user_data.get("rem_flow", "morning")
    user_id = update.effective_user.id

    if query.data == "rem_done":
        user = db.get_user(user_id)
        await query.edit_message_text(
            settings_display(user["first_name"], user["timezone"], user["morning_time"], user["evening_time"]),
            reply_markup=SETTINGS_KB)
        return ST_CHOOSE
    elif query.data == "rem_add":
        if db.get_reminder_count(user_id, flow) >= 10:
            await query.edit_message_text("Max 10 reminders! Remove one first.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back", callback_data="rem_done")]]))
            return ST_REM_ACTION
        await query.edit_message_text(f"Type your new {flow} reminder:")
        return ST_REM_ADD
    elif query.data == "rem_remove":
        reminders = db.get_reminders(user_id, flow)
        if not reminders:
            return await show_rem_menu(query, user_id, flow)
        kb = [[InlineKeyboardButton(f"❌ {r['reminder_text'][:30]}", callback_data=f"remid_{r['id']}")]
              for r in reminders]
        kb.append([InlineKeyboardButton("⬅️ Back", callback_data="rem_done")])
        await query.edit_message_text("Tap to remove:", reply_markup=InlineKeyboardMarkup(kb))
        return ST_REM_REMOVE
    return ST_REM_ACTION


async def st_rem_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text = update.message.text.strip()[:100]
    user_id = update.effective_user.id
    flow = context.user_data.get("rem_flow", "morning")
    db.add_reminder(user_id, flow, text)
    reminders = db.get_reminders(user_id, flow)
    lines = [f"  {i+1}. {r['reminder_text']}" for i, r in enumerate(reminders)]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add", callback_data="rem_add"),
         InlineKeyboardButton("➖ Remove", callback_data="rem_remove")],
        [InlineKeyboardButton("✅ Done", callback_data="rem_done")],
    ])
    await update.message.reply_text(f"Added! ✅\n\n{flow.title()} reminders:\n" + "\n".join(lines), reply_markup=kb)
    return ST_REM_ACTION


async def st_rem_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "rem_done":
        user = db.get_user(update.effective_user.id)
        await query.edit_message_text(
            settings_display(user["first_name"], user["timezone"], user["morning_time"], user["evening_time"]),
            reply_markup=SETTINGS_KB)
        return ST_CHOOSE
    if query.data.startswith("remid_"):
        rid = int(query.data.split("_")[1])
        db.remove_reminder(rid, update.effective_user.id)
    flow = context.user_data.get("rem_flow", "morning")
    return await show_rem_menu(query, update.effective_user.id, flow)


# ══════════════════════════════════════════════════════════════════════
# STANDALONE HANDLERS
# ══════════════════════════════════════════════════════════════════════

async def handle_today(query, user):
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user["user_id"], date)
    if not plan:
        await query.edit_message_text("No plan yet today. Tap ☀️ Morning to start!", reply_markup=back_menu_keyboard())
        return
    tasks = db.get_tasks_for_plan(plan["id"])
    if not tasks:
        await query.edit_message_text("Plan started but no tasks yet.", reply_markup=back_menu_keyboard())
        return
    formatted = format_tasks_by_category(tasks)
    status = format_task_status_summary(tasks)
    score = calculate_day_score(tasks)
    await query.edit_message_text(f"📋 Today ({date}):\n{formatted}\n\n📊 Status:\n{status}\n\n🎯 Score: {score}",
                                  reply_markup=back_menu_keyboard())


async def handle_memories(query, user_id):
    mem = db.get_random_memory(user_id)
    if mem:
        await query.edit_message_text(memory_recall(mem["moment"], mem["plan_date"]), reply_markup=back_menu_keyboard())
    else:
        await query.edit_message_text(no_memories(), reply_markup=back_menu_keyboard())


async def today_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = db.get_user(update.effective_user.id)
    if not user:
        await update.message.reply_text("Please /start first! 😊")
        return
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user["user_id"], date)
    if not plan:
        await update.message.reply_text("No plan yet. Tap ☀️ Morning!", reply_markup=main_menu_keyboard())
        return
    tasks = db.get_tasks_for_plan(plan["id"])
    if not tasks:
        await update.message.reply_text("Plan started, no tasks yet.", reply_markup=back_menu_keyboard())
        return
    formatted = format_tasks_by_category(tasks)
    score = calculate_day_score(tasks)
    await update.message.reply_text(f"📋 Today:\n{formatted}\n\n🎯 Score: {score}", reply_markup=back_menu_keyboard())


async def memories_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mem = db.get_random_memory(update.effective_user.id)
    if mem:
        await update.message.reply_text(memory_recall(mem["moment"], mem["plan_date"]), reply_markup=back_menu_keyboard())
    else:
        await update.message.reply_text(no_memories(), reply_markup=back_menu_keyboard())


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(help_text(), reply_markup=main_menu_keyboard())


async def voice_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(voice_not_supported(), reply_markup=main_menu_keyboard())


async def fallback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = db.get_user(update.effective_user.id)
    if user:
        # Check if this might be a plan (user typed tasks after clicking morning button)
        date = today_str(user["timezone"])
        plan = db.get_daily_plan(user["user_id"], date)
        if plan and not plan.get("morning_completed_at"):
            # They might be trying to enter tasks — guide them
            await update.message.reply_text(
                "Looks like you're trying to add tasks! Use /morning to start planning. 📝",
                reply_markup=main_menu_keyboard())
        else:
            await update.message.reply_text(fallback_msg(), reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text("Hey! Tap /start to get started 😊")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Error: {context.error}", exc_info=context.error)


# ══════════════════════════════════════════════════════════════════════
# SCHEDULER TRIGGERS
# ══════════════════════════════════════════════════════════════════════

async def trigger_morning_flow(user_id: int) -> None:
    user = db.get_user(user_id)
    if not user:
        return
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user_id, date)
    if plan and plan.get("morning_completed_at"):
        return  # Already done today

    reminders = get_flow_reminders(db, user_id, "morning")
    text = f"{morning_greeting(user['first_name'])}\n\nReminders:\n{format_reminders(reminders)}\n{morning_plan_prompt()}"
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("☀️ Start Planning", callback_data="menu_morning")]])
    await _app.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)
    if not plan:
        db.create_daily_plan(user_id, date)


async def trigger_evening_flow(user_id: int) -> None:
    user = db.get_user(user_id)
    if not user:
        return
    date = today_str(user["timezone"])
    plan = db.get_daily_plan(user_id, date)
    if plan and plan.get("evening_completed_at"):
        return  # Already done today

    if plan and plan.get("morning_completed_at"):
        tasks = db.get_tasks_for_plan(plan["id"])
        formatted = format_tasks_by_category(tasks)
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_review_prompt(formatted)}"
    else:
        text = f"{evening_greeting(user['first_name'])}\n\n{evening_no_plan()}"

    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌙 Start Review", callback_data="menu_evening")]])
    await _app.bot.send_message(chat_id=user_id, text=text, reply_markup=kb)


async def send_weekly_summary(user_id: int, reply_func) -> None:
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
    cat_breakdown = {}
    for t in tasks:
        cat_breakdown[t["category"]] = cat_breakdown.get(t["category"], 0) + 1
    streak = db.calculate_streak(user_id)

    try:
        insight = ai.generate_weekly_insight({
            "total_tasks": total, "completed": completed, "partial": partial,
            "skipped": skipped, "score_percentage": score_pct,
            "category_breakdown": cat_breakdown, "streak_days": streak})
    except Exception:
        insight = {"summary": "Keep it up!", "suggestions": "Stay consistent."}

    db.create_weekly_summary(user_id, {
        "week_start": week_start, "week_end": week_end, "total_tasks": total,
        "completed_tasks": completed, "partial_tasks": partial, "skipped_tasks": skipped,
        "score_percentage": score_pct, "category_breakdown": json.dumps(cat_breakdown),
        "ai_summary": insight.get("summary", ""), "ai_suggestions": insight.get("suggestions", ""),
        "streak_days": streak})

    emoji = {"work": "💼", "health": "🏃", "personal": "🏠", "learning": "📚", "other": "📌"}
    cats = "\n".join(f"  {emoji.get(c,'📌')} {c.title()}: {n}" for c, n in cat_breakdown.items())
    msg = (f"{weekly_summary_header()}\n\n📈 {score_pct}% ({completed}/{total})\n"
           f"🔶 Partial: {partial} | ⏭️ Skipped: {skipped}\n\n📊 Categories:\n{cats}\n\n"
           f"🔥 Streak: {streak} days\n\n💭 {insight.get('summary','')}\n💡 {insight.get('suggestions','')}")
    await reply_func(msg)


# ══════════════════════════════════════════════════════════════════════
# APP SETUP
# ══════════════════════════════════════════════════════════════════════

_app: Application = None  # type: ignore


def create_app(token: str, database: DatabaseManager, ai_client: GroqAIClient) -> Application:
    global db, ai, _app
    db = database
    ai = ai_client

    app = Application.builder().token(token).build()
    _app = app

    # Onboarding
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("start", start_command)],
        states={OB_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ob_name)]},
        fallbacks=[MessageHandler(filters.COMMAND, ob_command_fallback)],
        name="onboarding"))

    # Morning flow
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("morning", morning_command)],
        states={
            MF_PLAN: [MessageHandler(filters.TEXT & ~filters.COMMAND, mf_plan)],
            MF_CONFIRM: [
                CallbackQueryHandler(mf_confirm_callback, pattern="^mf_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, mf_confirm_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        name="morning"))

    # Evening flow
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("evening", evening_command)],
        states={
            EF_UPDATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ef_update)],
            EF_MEMORY: [
                CallbackQueryHandler(ef_memory_callback, pattern="^ef_memory_"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, ef_memory_text)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        name="evening"))

    # Settings
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("settings", settings_command)],
        states={
            ST_CHOOSE: [CallbackQueryHandler(st_choose)],
            ST_VALUE: [MessageHandler(filters.TEXT & ~filters.COMMAND, st_value)],
            ST_REM_ACTION: [CallbackQueryHandler(st_rem_action)],
            ST_REM_ADD: [MessageHandler(filters.TEXT & ~filters.COMMAND, st_rem_add)],
            ST_REM_REMOVE: [CallbackQueryHandler(st_rem_remove)],
        },
        fallbacks=[CommandHandler("cancel", cancel_handler)],
        name="settings"))

    # Menu callbacks (outside conversations)
    app.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))

    # Standalone commands
    app.add_handler(CommandHandler("today", today_command))
    app.add_handler(CommandHandler("memories", memories_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(MessageHandler(filters.VOICE | filters.VIDEO_NOTE, voice_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, fallback_handler))
    app.add_error_handler(error_handler)

    return app
