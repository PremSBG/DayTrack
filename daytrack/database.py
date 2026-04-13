"""
Database Module
===============
Database manager for DayTrack.
Supports both local SQLite (for development) and Turso cloud (for production).

- If TURSO_DATABASE_URL is set → uses Turso (libsql) with cloud persistence
- Otherwise → uses local SQLite file (daytrack.db)
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


def _create_connection(db_path: str = "daytrack.db"):
    """Create a database connection — Turso cloud or local SQLite."""
    turso_url = os.getenv("TURSO_DATABASE_URL", "")
    turso_token = os.getenv("TURSO_AUTH_TOKEN", "")

    if turso_url:
        # Use Turso (libsql) for cloud persistence
        import libsql_experimental as libsql
        conn = libsql.connect(
            db_path,
            sync_url=turso_url,
            auth_token=turso_token,
        )
        conn.sync()
        logger.info(f"Connected to Turso cloud: {turso_url}")
        return conn, True
    else:
        # Use local SQLite
        import sqlite3
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        logger.info(f"Connected to local SQLite: {db_path}")
        return conn, False


class DatabaseManager:
    """Database manager for DayTrack. Works with both SQLite and Turso."""

    def __init__(self, db_path: str = "daytrack.db"):
        self.db_path = db_path
        self.conn, self.is_turso = _create_connection(db_path)

    def _row_to_dict(self, row) -> Optional[dict]:
        """Convert a row to dict regardless of backend."""
        if row is None:
            return None
        if isinstance(row, dict):
            return row
        try:
            return dict(row)
        except (TypeError, ValueError):
            # libsql rows — access by column description
            if hasattr(self.conn, 'description') or hasattr(row, 'keys'):
                return dict(row)
            return None

    def _rows_to_dicts(self, rows) -> List[dict]:
        """Convert multiple rows to list of dicts."""
        result = []
        for row in rows:
            d = self._row_to_dict(row)
            if d:
                result.append(d)
        return result

    def _sync(self):
        """Sync with Turso cloud if using Turso."""
        if self.is_turso:
            try:
                self.conn.sync()
            except Exception as e:
                logger.warning(f"Turso sync failed: {e}")

    def init_schema(self) -> None:
        """Create all tables if they don't exist."""
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Kolkata',
                morning_time TEXT NOT NULL DEFAULT '07:00',
                evening_time TEXT NOT NULL DEFAULT '23:00',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                is_active INTEGER NOT NULL DEFAULT 1
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS custom_reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                flow_type TEXT NOT NULL CHECK(flow_type IN ('morning', 'evening')),
                reminder_text TEXT NOT NULL,
                display_order INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS daily_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                plan_date TEXT NOT NULL,
                raw_morning_input TEXT,
                raw_evening_input TEXT,
                day_score TEXT,
                moment TEXT,
                morning_completed_at TIMESTAMP,
                evening_completed_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                daily_plan_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                category TEXT NOT NULL CHECK(category IN ('work', 'health', 'personal', 'learning', 'other')),
                status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending', 'done', 'partial', 'skipped')),
                plan_date TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (daily_plan_id) REFERENCES daily_plans(id),
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS weekly_summaries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                week_start TEXT NOT NULL,
                week_end TEXT NOT NULL,
                total_tasks INTEGER DEFAULT 0,
                completed_tasks INTEGER DEFAULT 0,
                partial_tasks INTEGER DEFAULT 0,
                skipped_tasks INTEGER DEFAULT 0,
                score_percentage REAL DEFAULT 0.0,
                category_breakdown TEXT,
                ai_summary TEXT,
                ai_suggestions TEXT,
                streak_days INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            )
        """)

        self.conn.commit()
        self._sync()

    # ── User operations ──────────────────────────────────────────────

    def create_user(self, user_id: int, username: str, first_name: str,
                    timezone: str, morning_time: str, evening_time: str) -> None:
        self.conn.execute(
            "INSERT INTO users (user_id, username, first_name, timezone, morning_time, evening_time) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, username, first_name, timezone, morning_time, evening_time),
        )
        self.conn.commit()
        self._sync()

    def get_user(self, user_id: int) -> Optional[dict]:
        row = self.conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
        return self._row_to_dict(row)

    _ALLOWED_USER_FIELDS = frozenset(
        {"username", "first_name", "timezone", "morning_time", "evening_time", "is_active"}
    )

    def update_user_setting(self, user_id: int, field: str, value: str) -> None:
        if field not in self._ALLOWED_USER_FIELDS:
            raise ValueError(f"Invalid field '{field}'. Allowed: {sorted(self._ALLOWED_USER_FIELDS)}")
        self.conn.execute(f"UPDATE users SET {field} = ? WHERE user_id = ?", (value, user_id))
        self.conn.commit()
        self._sync()

    def get_active_users(self) -> List[dict]:
        rows = self.conn.execute("SELECT * FROM users WHERE is_active = 1").fetchall()
        return self._rows_to_dicts(rows)

    # ── Custom reminder operations ───────────────────────────────────

    def get_reminders(self, user_id: int, flow_type: str) -> List[dict]:
        rows = self.conn.execute(
            "SELECT * FROM custom_reminders WHERE user_id = ? AND flow_type = ? ORDER BY display_order",
            (user_id, flow_type),
        ).fetchall()
        return self._rows_to_dicts(rows)

    def add_reminder(self, user_id: int, flow_type: str, reminder_text: str) -> bool:
        count = self.get_reminder_count(user_id, flow_type)
        if count >= 10:
            return False
        self.conn.execute(
            "INSERT INTO custom_reminders (user_id, flow_type, reminder_text, display_order) VALUES (?, ?, ?, ?)",
            (user_id, flow_type, reminder_text, count + 1),
        )
        self.conn.commit()
        self._sync()
        return True

    def remove_reminder(self, reminder_id: int, user_id: int) -> bool:
        row = self.conn.execute(
            "SELECT flow_type, display_order FROM custom_reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        ).fetchone()
        if not row:
            return False
        r = self._row_to_dict(row)
        flow_type, deleted_order = r["flow_type"], r["display_order"]
        self.conn.execute("DELETE FROM custom_reminders WHERE id = ? AND user_id = ?", (reminder_id, user_id))
        self.conn.execute(
            "UPDATE custom_reminders SET display_order = display_order - 1 WHERE user_id = ? AND flow_type = ? AND display_order > ?",
            (user_id, flow_type, deleted_order),
        )
        self.conn.commit()
        self._sync()
        return True

    def set_default_reminders(self, user_id: int) -> None:
        defaults = [
            (user_id, "morning", "💧 Hydrate", 1),
            (user_id, "morning", "🧘 Stretch a little", 2),
            (user_id, "morning", "🌅 Take a deep breath", 3),
            (user_id, "evening", "🧴 Skincare", 1),
            (user_id, "evening", "💧 Drink water", 2),
            (user_id, "evening", "📖 Wind down", 3),
        ]
        self.conn.executemany(
            "INSERT INTO custom_reminders (user_id, flow_type, reminder_text, display_order) VALUES (?, ?, ?, ?)",
            defaults,
        )
        self.conn.commit()
        self._sync()

    def get_reminder_count(self, user_id: int, flow_type: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM custom_reminders WHERE user_id = ? AND flow_type = ?",
            (user_id, flow_type),
        ).fetchone()
        r = self._row_to_dict(row)
        return r["cnt"] if r else 0

    # ── Daily plan operations ────────────────────────────────────────

    def create_daily_plan(self, user_id: int, plan_date: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO daily_plans (user_id, plan_date) VALUES (?, ?)", (user_id, plan_date),
        )
        self.conn.commit()
        self._sync()
        return cursor.lastrowid

    def get_daily_plan(self, user_id: int, plan_date: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM daily_plans WHERE user_id = ? AND plan_date = ?", (user_id, plan_date),
        ).fetchone()
        return self._row_to_dict(row)

    def update_daily_plan(self, plan_id: int, **fields) -> None:
        allowed = {"raw_morning_input", "raw_evening_input", "day_score", "moment",
                    "morning_completed_at", "evening_completed_at"}
        for k in fields:
            if k not in allowed:
                raise ValueError(f"Invalid daily_plan field: {k}")
        sets = ", ".join(f"{k} = ?" for k in fields)
        vals = list(fields.values()) + [plan_id]
        self.conn.execute(f"UPDATE daily_plans SET {sets} WHERE id = ?", vals)
        self.conn.commit()
        self._sync()

    # ── Task operations ──────────────────────────────────────────────

    def create_tasks(self, daily_plan_id: int, user_id: int, plan_date: str, tasks: List[dict]) -> None:
        rows = [(daily_plan_id, user_id, t["title"], t["category"], plan_date) for t in tasks]
        self.conn.executemany(
            "INSERT INTO tasks (daily_plan_id, user_id, title, category, plan_date) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        self.conn.commit()
        self._sync()

    def get_tasks_for_plan(self, daily_plan_id: int) -> List[dict]:
        rows = self.conn.execute("SELECT * FROM tasks WHERE daily_plan_id = ?", (daily_plan_id,)).fetchall()
        return self._rows_to_dicts(rows)

    def update_task_status(self, task_id: int, status: str) -> None:
        valid = {"pending", "done", "partial", "skipped"}
        if status not in valid:
            raise ValueError(f"Invalid status '{status}'. Allowed: {valid}")
        self.conn.execute("UPDATE tasks SET status = ? WHERE id = ?", (status, task_id))
        self.conn.commit()
        self._sync()

    def get_tasks_for_week(self, user_id: int, week_start: str, week_end: str) -> List[dict]:
        rows = self.conn.execute(
            "SELECT * FROM tasks WHERE user_id = ? AND plan_date BETWEEN ? AND ?",
            (user_id, week_start, week_end),
        ).fetchall()
        return self._rows_to_dicts(rows)

    # ── Weekly summary operations ────────────────────────────────────

    def create_weekly_summary(self, user_id: int, summary_data: dict) -> None:
        self.conn.execute(
            """INSERT INTO weekly_summaries
               (user_id, week_start, week_end, total_tasks, completed_tasks,
                partial_tasks, skipped_tasks, score_percentage, category_breakdown,
                ai_summary, ai_suggestions, streak_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, summary_data["week_start"], summary_data["week_end"],
             summary_data.get("total_tasks", 0), summary_data.get("completed_tasks", 0),
             summary_data.get("partial_tasks", 0), summary_data.get("skipped_tasks", 0),
             summary_data.get("score_percentage", 0.0), summary_data.get("category_breakdown", "{}"),
             summary_data.get("ai_summary", ""), summary_data.get("ai_suggestions", ""),
             summary_data.get("streak_days", 0)),
        )
        self.conn.commit()
        self._sync()

    def get_weekly_summary(self, user_id: int, week_start: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM weekly_summaries WHERE user_id = ? AND week_start = ?", (user_id, week_start),
        ).fetchone()
        return self._row_to_dict(row)

    # ── Memory & streak operations ───────────────────────────────────

    def get_random_memory(self, user_id: int) -> Optional[dict]:
        row = self.conn.execute(
            """SELECT moment, plan_date FROM daily_plans
               WHERE user_id = ? AND moment IS NOT NULL AND moment != ''
               ORDER BY RANDOM() LIMIT 1""",
            (user_id,),
        ).fetchone()
        return self._row_to_dict(row)

    def calculate_streak(self, user_id: int) -> int:
        rows = self.conn.execute(
            """SELECT plan_date FROM daily_plans
               WHERE user_id = ? AND morning_completed_at IS NOT NULL
                 AND evening_completed_at IS NOT NULL
               ORDER BY plan_date DESC""",
            (user_id,),
        ).fetchall()
        if not rows:
            return 0
        streak = 0
        plans = self._rows_to_dicts(rows)
        expected = datetime.strptime(plans[0]["plan_date"], "%Y-%m-%d").date()
        for p in plans:
            d = datetime.strptime(p["plan_date"], "%Y-%m-%d").date()
            if d == expected:
                streak += 1
                expected -= timedelta(days=1)
            else:
                break
        return streak
