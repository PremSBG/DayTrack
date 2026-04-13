# DayTrack — Daily Companion Telegram Bot 🌅🌙

A Telegram bot that acts as your personal daily companion. It greets you morning and evening, helps you plan and review your day through natural conversation, captures memories, and sends gentle reminders.

It feels like talking to a thoughtful friend, not using a productivity app.

## What It Does

**Morning Flow** (at your chosen time)
- Warm greeting with your name
- Your custom morning reminders (hydrate, stretch, listen to music — whatever you set)
- Asks "What's your plan for today?" — you reply naturally
- AI parses your paragraph into structured tasks with categories
- Confirms tasks back to you

**Evening Flow** (at your chosen time)
- Shows your morning tasks, asks "How did your day go?"
- AI matches your update against tasks → marks each as done/partial/skipped
- Shows your day score (e.g., 4/6 done)
- Asks if you want to save a memory or thought from today
- Your custom evening reminders + goodnight message

**Weekly Summary** (Sunday evening)
- Task completion stats and category breakdown
- AI-generated reflection and suggestions
- Streak info

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Set up your profile (name, timezone, reminder times) |
| `/today` | See today's plan and task statuses |
| `/settings` | Update name, timezone, times, or custom reminders |
| `/memories` | Revisit a random past memory you saved |
| `/help` | List available commands |

## Setup Guide

### Step 1: Get API Keys

1. **Telegram Bot Token**: Message [@BotFather](https://t.me/BotFather) on Telegram → `/newbot` → follow prompts → copy the token
2. **Groq API Key**: Sign up at [console.groq.com](https://console.groq.com/) (free) → API Keys → create one

### Step 2: Set Up Turso Database (Free, 2 minutes)

This gives you a cloud database that persists across deploys.

```bash
# Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash

# Sign up / login
turso auth signup    # or: turso auth login

# Create a database
turso db create daytrack

# Get your credentials
turso db show --url daytrack
# → outputs something like: libsql://daytrack-yourname.turso.io

turso db tokens create daytrack
# → outputs a long token string
```

Save both values — you'll need them in Step 3.

### Step 3: Test Locally

```bash
git clone https://github.com/YOUR_USERNAME/daytrack-bot.git
cd daytrack-bot
pip install -r requirements.txt
cp env.example .env
```

Edit `.env` and fill in:
```
TELEGRAM_BOT_TOKEN=your_token
GROQ_API_KEY=your_key
TURSO_DATABASE_URL=libsql://daytrack-yourname.turso.io
TURSO_AUTH_TOKEN=your_turso_token
```

Run:
```bash
python main.py
```

Open Telegram → find your bot → send `/start`. If onboarding works, you're good.

### Step 4: Deploy on Render.com

1. Push your code to GitHub (`.gitignore` already excludes `.env`)
2. Go to [render.com](https://render.com) → sign up → "New +" → "Background Worker"
3. Connect your GitHub repo — Render auto-detects `render.yaml`
4. Go to "Environment" tab → add these 4 env vars:
   - `TELEGRAM_BOT_TOKEN` = your token
   - `GROQ_API_KEY` = your key
   - `TURSO_DATABASE_URL` = your Turso URL
   - `TURSO_AUTH_TOKEN` = your Turso token
5. Click "Create Background Worker"

Your bot is now live 24/7.

### Step 5: Share With Others

Share your bot link: `https://t.me/YOUR_BOT_USERNAME`

Anyone who messages the bot gets their own profile with their own timezone, reminder times, custom reminders, tasks, and memories. All stored per-user in the cloud database.

## How the Database Works

- **Development**: If no `TURSO_DATABASE_URL` is set, the bot uses a local `daytrack.db` SQLite file. Simple, zero setup.
- **Production**: With Turso, data lives in the cloud. Even if Render restarts or redeploys your worker, all user data persists. Turso's free tier gives you 9GB — more than enough for thousands of users.

The schema is auto-created on first run. No manual database setup needed.

## Defaults

- Timezone: Asia/Kolkata (configurable per user)
- Morning time: 07:00 (configurable)
- Evening time: 23:00 (configurable)
- Morning reminders: Hydrate, Stretch, Take a deep breath (customizable)
- Evening reminders: Skincare, Drink water, Wind down (customizable)

## Tech Stack

- Python + [python-telegram-bot](https://python-telegram-bot.org/)
- [Turso](https://turso.tech/) / SQLite (cloud or local database)
- [Groq AI](https://groq.com/) (free tier, LLaMA model)
- APScheduler (per-user scheduled messages)

## Project Structure

```
daytrack/
├── __init__.py        # Package init
├── config.py          # Environment-based configuration
├── database.py        # Database manager (Turso cloud or local SQLite)
├── ai_client.py       # Groq AI client
├── bot.py             # Telegram handlers & conversation flows
├── scheduler.py       # Per-user scheduling
├── messages.py        # Message templates
├── utils.py           # Validators & formatters
main.py                # Entry point
env.example            # Environment variable template
requirements.txt       # Python dependencies
render.yaml            # Render.com deployment config
```

## License

MIT
