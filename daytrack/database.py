"""
Database Module
===============
Database manager for DayTrack.
- If TURSO_DATABASE_URL is set → uses Turso HTTP API (persistent cloud)
- Otherwise → uses local SQLite (development only)
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Schema SQL shared between both backends
SCHEMA_STATEMENTS = [
    """CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY, username TEXT, first_name TEXT NOT NULL,
        timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
        morning_time TEXT NOT NULL DEFAULT '07:00',
        evening_time TEXT NOT NULL DEFAULT '23:00',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        is_active INTEGER NOT NULL DEFAULT 1)""",
    """CREATE TABLE IF NOT EXISTS custom_reminders (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        flow_type TEXT NOT NULL CHECK(flow_type IN ('morning', 'evening')),
        reminder_text TEXT NOT NULL, display_order INTEGER NOT NULL DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id))""",
    """CREATE TABLE IF NOT EXISTS daily_plans (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        plan_date TEXT NOT NULL, raw_morning_input TEXT, raw_evening_input TEXT,
        day_score TEXT, moment TEXT,
        morning_completed_at TIMESTAMP, evening_completed_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id))""",
    """CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, daily_plan_id INTEGER NOT NULL,
        user_id INTEGER NOT NULL, title TEXT NOT NULL,
        category TEXT NOT NULL CHECK(category IN ('work','health','personal','learning','other')),
        status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','done','partial','skipped')),
        plan_date TEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (daily_plan_id) REFERENCES daily_plans(id),
        FOREIGN KEY (user_id) REFERENCES users(user_id))""",
    """CREATE TABLE IF NOT EXISTS weekly_summaries (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL,
        week_start TEXT NOT NULL, week_end TEXT NOT NULL,
        total_tasks INTEGER DEFAULT 0, completed_tasks INTEGER DEFAULT 0,
        partial_tasks INTEGER DEFAULT 0, skipped_tasks INTEGER DEFAULT 0,
        score_percentage REAL DEFAULT 0.0, category_breakdown TEXT,
        ai_summary TEXT, ai_suggestions TEXT, streak_days INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(user_id))""",
]


class DatabaseManager:
    """Database manager — uses Turso HTTP API for cloud persistence."""

    def __init__(self, db_path: str = "daytrack.db"):
        turso_url = os.getenv("TURSO_DATABASE_URL", "")
        turso_token = os.getenv("TURSO_AUTH_TOKEN", "")

        if not turso_url or not turso_token:
            raise ValueError(
                "TURSO_DATABASE_URL and TURSO_AUTH_TOKEN are required.\n"
                "Set up Turso: https://turso.tech → create a database → get URL and token."
            )

        from daytrack.turso_client import TursoClient
        self.turso = TursoClient(turso_url, turso_token)
        logger.info(f"Connected to Turso: {turso_url}")

    def _exec(self, sql: str, args: list = None) -> dict:
        return self.turso.execute(sql, args or [])

    def _fetchall(self, sql: str, args: list = None) -> List[dict]:
        result = self.turso.execute(sql, args or [])
        return self.turso.rows_to_dicts(result)

    def _fetchone(self, sql: str, args: list = None) -> Optional[dict]:
        result = self.turso.execute(sql, args or [])
        return self.turso.first_row(result)

    def _insert(self, sql: str, args: list = None) -> int:
        result = self.turso.execute(sql, args or [])
        return self.turso.last_insert_id(result)

    def _write(self, sql: str, args: list = None) -> None:
        self.turso.execute(sql, args or [])

    def init_schema(self) -> None:
        for sql in SCHEMA_STATEMENTS:
            self._write(sql)

    # ── User operations ──────────────────────────────────────────────

    def create_user(self, user_id: int, username: str, first_name: str,
                    timezone: str, morning_time: str, evening_time: str) -> None:
        self._write(
            "INSERT INTO users (user_id,username,first_name,timezone,morning_time,evening_time) VALUES (?,?,?,?,?,?)",
            [user_id, username, first_name, timezone, morning_time, evening_time])

    def get_user(self, user_id: int) -> Optional[dict]:
        return self._fetchone("SELECT * FROM users WHERE user_id = ?", [user_id])

    _ALLOWED = {"username","first_name","timezone","morning_time","evening_time","is_active"}

    def update_user_setting(self, user_id: int, field: str, value) -> None:
        if field not in self._ALLOWED:
            raise ValueError(f"Invalid field: {field}")
        self._write(f"UPDATE users SET {field} = ? WHERE user_id = ?", [value, user_id])

    def get_active_users(self) -> List[dict]:
        return self._fetchall("SELECT * FROM users WHERE is_active = 1")

    # ── Custom reminder operations ───────────────────────────────────

    def get_reminders(self, user_id: int, flow_type: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM custom_reminders WHERE user_id=? AND flow_type=? ORDER BY display_order",
            [user_id, flow_type])

    def add_reminder(self, user_id: int, flow_type: str, reminder_text: str) -> bool:
        count = self.get_reminder_count(user_id, flow_type)
        if count >= 10:
            return False
        self._write(
            "INSERT INTO custom_reminders (user_id,flow_type,reminder_text,display_order) VALUES (?,?,?,?)",
            [user_id, flow_type, reminder_text, count + 1])
        return True

    def remove_reminder(self, reminder_id: int, user_id: int) -> bool:
        row = self._fetchone(
            "SELECT flow_type,display_order FROM custom_reminders WHERE id=? AND user_id=?",
            [reminder_id, user_id])
        if not row:
            return False
        self._write("DELETE FROM custom_reminders WHERE id=? AND user_id=?", [reminder_id, user_id])
        self._write(
            "UPDATE custom_reminders SET display_order=display_order-1 WHERE user_id=? AND flow_type=? AND display_order>?",
            [user_id, row["flow_type"], row["display_order"]])
        return True

    def set_default_reminders(self, user_id: int) -> None:
        defaults = [
            (user_id, "morning", "💧 Hydrate", 1), (user_id, "morning", "🧘 Stretch", 2),
            (user_id, "morning", "🌅 Deep breath", 3), (user_id, "evening", "🧴 Skincare", 1),
            (user_id, "evening", "💧 Water", 2), (user_id, "evening", "📖 Wind down", 3),
        ]
        for d in defaults:
            self._write(
                "INSERT INTO custom_reminders (user_id,flow_type,reminder_text,display_order) VALUES (?,?,?,?)",
                list(d))

    def get_reminder_count(self, user_id: int, flow_type: str) -> int:
        row = self._fetchone(
            "SELECT COUNT(*) as cnt FROM custom_reminders WHERE user_id=? AND flow_type=?",
            [user_id, flow_type])
        return int(row["cnt"]) if row else 0

    # ── Daily plan operations ────────────────────────────────────────

    def create_daily_plan(self, user_id: int, plan_date: str) -> int:
        return self._insert("INSERT INTO daily_plans (user_id,plan_date) VALUES (?,?)", [user_id, plan_date])

    def get_daily_plan(self, user_id: int, plan_date: str) -> Optional[dict]:
        return self._fetchone("SELECT * FROM daily_plans WHERE user_id=? AND plan_date=?", [user_id, plan_date])

    def update_daily_plan(self, plan_id: int, **fields) -> None:
        allowed = {"raw_morning_input","raw_evening_input","day_score","moment","morning_completed_at","evening_completed_at"}
        for k in fields:
            if k not in allowed:
                raise ValueError(f"Invalid field: {k}")
        sets = ", ".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [plan_id]
        self._write(f"UPDATE daily_plans SET {sets} WHERE id=?", vals)

    # ── Task operations ──────────────────────────────────────────────

    def create_tasks(self, daily_plan_id: int, user_id: int, plan_date: str, tasks: List[dict]) -> None:
        for t in tasks:
            self._write(
                "INSERT INTO tasks (daily_plan_id,user_id,title,category,plan_date) VALUES (?,?,?,?,?)",
                [daily_plan_id, user_id, t["title"], t["category"], plan_date])

    def get_tasks_for_plan(self, daily_plan_id: int) -> List[dict]:
        return self._fetchall("SELECT * FROM tasks WHERE daily_plan_id=?", [daily_plan_id])

    def update_task_status(self, task_id: int, status: str) -> None:
        valid = {"pending","done","partial","skipped"}
        if status not in valid:
            raise ValueError(f"Invalid status: {status}")
        self._write("UPDATE tasks SET status=? WHERE id=?", [status, task_id])

    def get_tasks_for_week(self, user_id: int, week_start: str, week_end: str) -> List[dict]:
        return self._fetchall(
            "SELECT * FROM tasks WHERE user_id=? AND plan_date BETWEEN ? AND ?",
            [user_id, week_start, week_end])

    # ── Weekly summary, memory, streak ───────────────────────────────

    def create_weekly_summary(self, user_id: int, d: dict) -> None:
        self._write(
            """INSERT INTO weekly_summaries (user_id,week_start,week_end,total_tasks,completed_tasks,
               partial_tasks,skipped_tasks,score_percentage,category_breakdown,ai_summary,ai_suggestions,streak_days)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            [user_id, d["week_start"], d["week_end"], d.get("total_tasks",0), d.get("completed_tasks",0),
             d.get("partial_tasks",0), d.get("skipped_tasks",0), d.get("score_percentage",0.0),
             d.get("category_breakdown","{}"), d.get("ai_summary",""), d.get("ai_suggestions",""), d.get("streak_days",0)])

    def get_random_memory(self, user_id: int) -> Optional[dict]:
        return self._fetchone(
            "SELECT moment,plan_date FROM daily_plans WHERE user_id=? AND moment IS NOT NULL AND moment!='' ORDER BY RANDOM() LIMIT 1",
            [user_id])

    def calculate_streak(self, user_id: int) -> int:
        rows = self._fetchall(
            "SELECT plan_date FROM daily_plans WHERE user_id=? AND morning_completed_at IS NOT NULL AND evening_completed_at IS NOT NULL ORDER BY plan_date DESC",
            [user_id])
        if not rows:
            return 0
        streak = 0
        expected = datetime.strptime(rows[0]["plan_date"], "%Y-%m-%d").date()
        for row in rows:
            d = datetime.strptime(row["plan_date"], "%Y-%m-%d").date()
            if d == expected:
                streak += 1
                expected -= timedelta(days=1)
            else:
                break
        return streak
