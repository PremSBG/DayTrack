"""
Messages Module — warm conversational templates for DayTrack.
"""
import random


def welcome_new() -> str:
    return "Hey there! 👋 Welcome to DayTrack — your daily companion.\n\nWhat should I call you? Just type your name."


def welcome_back(name: str) -> str:
    return f"Hey {name}! 👋 What would you like to do?"


def onboarding_complete(name: str) -> str:
    return (
        f"All set, {name}! 🎉\n\n"
        "☀️ Morning check-in: 7:00 AM\n"
        "🌙 Evening check-in: 11:00 PM\n"
        "📝 Default reminders set\n\n"
        "What would you like to do?"
    )


def morning_greeting(name: str) -> str:
    g = [f"Good morning, {name}! ☀️", f"Hey {name}! 🌅 New day, new plans.", f"Morning, {name}! 🌞"]
    return random.choice(g)


def morning_plan_prompt() -> str:
    return (
        "\nWhat's your plan for today? 📝\n\n"
        "Just type your tasks naturally, like:\n"
        "\"Gym, finish report, call mom, read 20 pages\""
    )


def morning_tasks_confirmation(formatted: str) -> str:
    return f"Here's what I got:\n{formatted}"


def morning_tasks_saved() -> str:
    return "Plan saved! Have a great day 🚀"


def morning_already_done() -> str:
    return "You already planned today! ☀️"


def evening_greeting(name: str) -> str:
    g = [f"Hey {name}! 🌙", f"Evening, {name}! 🌇", f"Hey {name}! 🌛 Let's wrap up."]
    return random.choice(g)


def evening_review_prompt(formatted: str) -> str:
    return f"Here's what you planned:\n{formatted}\n\nHow did your day go? Tell me naturally."


def evening_no_plan() -> str:
    return "No plan set today — no worries! How was your day? 💭"


def evening_score(score: str, summary: str) -> str:
    return f"Score: {score} 🎯\n\n{summary}"


def evening_memory_prompt() -> str:
    return "Any memory or thought from today?"


def evening_memory_saved() -> str:
    return "Saved! 💝"


def evening_already_done() -> str:
    return "You already reviewed today! 🌙"


def goodnight(name: str) -> str:
    g = [f"Goodnight, {name}! 🌙", f"Sleep well, {name}! 💤", f"Rest well, {name}! 🌟"]
    return random.choice(g)


def help_text() -> str:
    return (
        "Here's what I can do:\n\n"
        "☀️ Morning — plan your day\n"
        "🌙 Evening — review your day\n"
        "📋 Today — see current plan\n"
        "⚙️ Settings — change preferences\n"
        "💭 Memories — random past memory\n\n"
        "I also check in at 7 AM and 11 PM! 💬"
    )


def voice_not_supported() -> str:
    return "Can't do voice yet — type it out for me? 🙏"


def fallback_msg() -> str:
    return "Not sure what to do with that. Here's what I can help with:"


def settings_display(name, tz, morning, evening) -> str:
    return (
        f"⚙️ Your settings:\n\n"
        f"👤 Name: {name}\n"
        f"☀️ Morning: {morning}\n"
        f"🌙 Evening: {evening}\n"
    )


def weekly_no_tasks() -> str:
    return "Easy week — no tasks recorded. Fresh start next week! 🌱"


def weekly_summary_header() -> str:
    return "📊 Weekly Summary"


def memory_recall(moment: str, date: str) -> str:
    return f"💭 On {date}:\n\n\"{moment}\""


def no_memories() -> str:
    return "No memories saved yet. They'll show up after your evening check-ins! 💫"
