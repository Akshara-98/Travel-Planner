import sqlite3
from datetime import datetime
from typing import Any, Dict, Optional


DB_PATH = None


def init_db(db_path: str):
    global DB_PATH
    DB_PATH = db_path
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS planning_requests (
            execution_id TEXT PRIMARY KEY,
            destination TEXT,
            start_date TEXT,
            end_date TEXT,
            travelers INTEGER,
            budget TEXT,
            email TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            payload TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id TEXT PRIMARY KEY,
            execution_id TEXT,
            destination TEXT,
            start_date TEXT,
            end_date TEXT,
            travelers INTEGER,
            budget TEXT,
            email TEXT,
            status TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            approved_at TEXT,
            plan_json TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def get_connection() -> sqlite3.Connection:
    if DB_PATH is None:
        raise RuntimeError("Database was not initialized")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def upsert_request(execution_id: str, destination: str, start_date: str, end_date: str, travelers: int, budget: str, email: str, status: str, payload: Optional[Dict[str, Any]] = None):
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT INTO planning_requests (execution_id, destination, start_date, end_date, travelers, budget, email, status, payload)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(execution_id)
            DO UPDATE SET destination=excluded.destination,
                          start_date=excluded.start_date,
                          end_date=excluded.end_date,
                          travelers=excluded.travelers,
                          budget=excluded.budget,
                          email=excluded.email,
                          status=excluded.status,
                          payload=excluded.payload
            """,
            (
                execution_id,
                destination,
                start_date,
                end_date,
                travelers,
                budget,
                email,
                status,
                __import__("json").dumps(payload or {}, default=str),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def save_plan(plan: Dict[str, Any], execution_id: str):
    plan_id = plan.get("plan_id") or f"plan-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{execution_id[:8]}"
    conn = get_connection()
    try:
        conn.execute(
            """
            INSERT OR REPLACE INTO plans (
                id, execution_id, destination, start_date, end_date, travelers, budget, email, status, approved_at, plan_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                execution_id,
                plan.get("destination"),
                plan.get("start_date"),
                plan.get("end_date"),
                plan.get("travelers"),
                plan.get("budget"),
                plan.get("email"),
                plan.get("status", "pending"),
                plan.get("approved_at"),
                __import__("json").dumps(plan, default=str),
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return plan_id


def get_plan_by_execution(execution_id: str):
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM plans WHERE execution_id = ? ORDER BY created_at DESC LIMIT 1", (execution_id,)).fetchone()
        if not row:
            return None
        return dict(row)
    finally:
        conn.close()


def update_plan_status(plan_id: str, status: str, approved_at: Optional[str] = None):
    conn = get_connection()
    try:
        conn.execute(
            "UPDATE plans SET status = ?, approved_at = ? WHERE id = ?",
            (status, approved_at, plan_id),
        )
        conn.commit()
    finally:
        conn.close()
