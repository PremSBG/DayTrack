"""
Messages Module
===============
Warm, conversational message templates for DayTrack.
"""

import random


# ── Morning messages ─────────────────────────────────────────────────

def morning_greeting(name: str) -> str:
    greetings = [
        f"Good morning, {name}! ☀️ Hope you slept well.",
        f"Hey {name}! 🌅 Rise and shine, a new day awaits.",
        f"Morning, {name}! 🌞 Let's make today count.",
        f"Good morning, {name}! ☕ Ready for a great day?",
    ]
    return random.choice(greetings)


def morning_plan_prompt() -> str:
    return "\nWhat's your plan for today? Just tell me in your own words — a paragraph, a list, whatever feels natural. 📝"


def morning_tasks_confirmation(formatted_tasks: str) -> str:
    return (
        f"Here's what I got from your plan:\n{formatted_tasks}\n\n"
        "Does this look good? Say 'yes' to confirm, or tell me what to change. 😊"
    )


def morning_tasks_saved() -> str:
    return "Awesome, your plan is set! Have a wonderful day. 🚀"


# ── Evening messages ─────────────────────────────────────────────────

def evening_greeting(name: str) -> str:
    greetings = [
        f"Hey {name}! 🌙 How was your day?",
        f"Good evening, {name}! 🌆 Time to wind down.",
        f"Evening, {name}! 🌇 Let's see how today went.",
        f"Hey {name}! 🌛 Ready to wrap up the day?",
    ]
    return random.choice(greetings)


def evening_review_prompt(formatted_tasks: str) -> str:
    return (
        f"Here's what you planned this morning:\n{formatted_tasks}\n\n"
        "How did your day go? Just tell me naturally. 💬"
    )


def evening_no_plan() -> str:
    return "Looks like you didn't set a plan this morning — no worries at all! How was your day? Any reflections? 💭"


def evening_score(score: str, status_summary: str) -> str:
    return f"Your day score: {score} 🎯\n\n{status_summary}"


def evening_memory_prompt() -> str:
    return "\nAny moment, memory, or thought you want to remember from today? Happy, sad, anything — totally optional. 💫"


def evening_memory_saved() -> str:
    return "Saved that memory for you. 💝"


def goodnight(name: str) -> str:
    messages = [
        f"Goodnight, {name}! 🌙 Sleep well.",
        f"Sweet dreams, {name}! 💤 See you tomorrow.",
        f"Rest well, {name}! 🌟 Tomorrow's a fresh start.",
    ]
    return random.choice(messages)


# ── Onboarding messages ─────────────────────────────────────────────

def welcome_new() -> str:
    return (
        "Hey there! 👋 Welcome to DayTrack — your personal daily companion.\n\n"
        "I'll help you plan your mornings, review your evenings, and capture little moments along the way.\n\n"
        "Let's get you set up! What should I call you? 😊"
    )


def welcome_back(name: str) -> str:
    return (
        f"Welcome back, {name}! 👋 Good to see you.\n\n"
        "Here's what I can do:\n"
        "  /today — See today's plan\n"
        "  /settings — Update your preferences\n"
        "  /memories — Revisit a past memory\n"
        "  /help — See all commands"
    )


def ask_timezone() -> str:
    return (
        "What timezone are you in? 🌍\n\n"
        "Just type it like: Asia/Kolkata, America/New_York, Europe/London\n"
        "(Or press skip to use Asia/Kolkata as default)"
    )


def ask_morning_time() -> str:
    return (
        "When should I send your morning greeting? ⏰\n\n"
        "Type a time in HH:MM format (24-hour), like 07:00\n"
        "(Or press skip for the default: 07:00)"
    )


def ask_evening_time() -> str:
    return (
        "And when should I check in with you in the evening? 🌙\n\n"
        "Type a time in HH:MM format (24-hour), like 23:00\n"
        "(Or press skip for the default: 23:00)"
    )


def ask_custom_reminders() -> str:
    return (
        "Here are some gentle reminders I can send you each morning and evening:\n\n"
        "🌅 Morning: Hydrate, Stretch, Take a deep breath\n"
        "🌙 Evening: Skincare, Drink water, Wind down\n\n"
        "Want to keep these, or set your own? You can always change them later in /settings.\n"
        "Type 'keep' to use defaults, or tell me what you'd like!"
    )


def onboarding_complete(name: str, tz: str) -> str:
    return (
        f"All set, {name}! 🎉 Here's your setup:\n\n"
        f"  🌍 Timezone: {tz}\n"
        f"  ☀️ Morning: 07:00 AM\n"
        f"  🌙 Evening: 11:00 PM\n\n"
        "I'll see you at your next scheduled time. Have a great one! 🚀"
    )


# ── Settings messages ────────────────────────────────────────────────

def settings_menu(name: str, tz: str, morning: str, evening: str) -> str:
    return (
        f"Here are your current settings, {name}:\n\n"
        f"  👤 Name: {name}\n"
        f"  🌍 Timezone: {tz}\n"
        f"  ☀️ Morning time: {morning}\n"
        f"  🌙 Evening time: {evening}\n\n"
        "What would you like to update?"
    )


# ── Help & fallback ─────────────────────────────────────────────────

def help_text() -> str:
    return (
        "Here's what I can do:\n\n"
        "  /start — Set up your profile\n"
        "  /today — See today's plan and status\n"
        "  /settings — Update your preferences\n"
        "  /memories — Revisit a random past memory\n"
        "  /help — Show this message\n\n"
        "Or just chat with me during our morning and evening check-ins! 💬"
    )


def voice_not_supported() -> str:
    return "I can't listen to voice messages just yet — could you type that out for me instead? 🙏"


def fallback() -> str:
    messages = [
        "Hmm, I'm not sure what to do with that. Try /help to see what I can do! 😊",
        "I didn't quite catch that. Use /help to see available commands! 💬",
    ]
    return random.choice(messages)


# ── Weekly summary ───────────────────────────────────────────────────

def weekly_summary_header() -> str:
    return "📊 Here's your weekly summary!"


def weekly_no_tasks() -> str:
    return (
        "Looks like you took it easy this week — no tasks recorded. "
        "That's totally fine! Fresh start next week. 🌱"
    )


def memory_recall(moment: str, date: str) -> str:
    return f"💭 On {date}, you wrote:\n\n\"{moment}\""


def no_memories() -> str:
    return "You haven't saved any memories yet. They'll show up here once you share some during our evening chats! 💫"
