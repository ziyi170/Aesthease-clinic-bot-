"""
SQLite database layer — 4 tables (Repo 3 / DentalDesk pattern).
Repo 3 had 4 tables vs our original 3. Added: message_queue table
to support asyncio.Queue deduplication.
"""
import sqlite3
import os
from datetime import datetime
from typing import Optional
from src.shared.models import Patient, Appointment

DB_PATH = os.getenv("DB_PATH", "data/clinic.db")


def get_connection():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all 4 tables. Run once on startup."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS patients (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            phone       TEXT UNIQUE NOT NULL,
            name        TEXT NOT NULL,
            age         INTEGER,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS appointments (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_phone    TEXT NOT NULL,
            patient_name     TEXT NOT NULL,
            service          TEXT NOT NULL,
            datetime_str     TEXT NOT NULL,
            google_event_id  TEXT,
            status           TEXT DEFAULT 'confirmed',
            created_at       TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS messages (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            phone      TEXT NOT NULL,
            role       TEXT NOT NULL,
            content    TEXT NOT NULL,
            timestamp  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS processed_messages (
            message_id  TEXT PRIMARY KEY,
            processed_at TEXT DEFAULT (datetime('now'))
        );
    """)
    conn.commit()
    conn.close()
    print("Database initialised — 4 tables ready.")


# ── Idempotency check (Repo 3: prevent duplicate processing) ──────────────────

def is_already_processed(message_id: str) -> bool:
    conn = get_connection()
    row = conn.execute(
        "SELECT 1 FROM processed_messages WHERE message_id = ?", (message_id,)
    ).fetchone()
    conn.close()
    return row is not None


def mark_as_processed(message_id: str):
    conn = get_connection()
    conn.execute(
        "INSERT OR IGNORE INTO processed_messages (message_id) VALUES (?)", (message_id,)
    )
    conn.commit()
    conn.close()


# ── Patient operations ────────────────────────────────────────────────────────

def get_patient(phone: str) -> Optional[Patient]:
    conn = get_connection()
    row = conn.execute("SELECT * FROM patients WHERE phone = ?", (phone,)).fetchone()
    conn.close()
    return Patient(**dict(row)) if row else None


def create_patient(patient: Patient) -> Patient:
    conn = get_connection()
    conn.execute(
        "INSERT INTO patients (phone, name, age) VALUES (?, ?, ?)",
        (patient.phone, patient.name, patient.age)
    )
    conn.commit()
    conn.close()
    return patient


# ── Appointment operations ────────────────────────────────────────────────────

def create_appointment(appt: Appointment) -> Appointment:
    conn = get_connection()
    conn.execute(
        """INSERT INTO appointments
           (patient_phone, patient_name, service, datetime_str, google_event_id, status)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (appt.patient_phone, appt.patient_name, appt.service,
         appt.datetime_str, appt.google_event_id, appt.status)
    )
    conn.commit()
    conn.close()
    return appt


def get_appointments_by_phone(phone: str) -> list[Appointment]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM appointments WHERE patient_phone = ? AND status = 'confirmed'", (phone,)
    ).fetchall()
    conn.close()
    return [Appointment(**dict(r)) for r in rows]


def cancel_appointment(appt_id: int):
    conn = get_connection()
    conn.execute("UPDATE appointments SET status = 'cancelled' WHERE id = ?", (appt_id,))
    conn.commit()
    conn.close()


# ── Message / memory operations ───────────────────────────────────────────────

def save_message(phone: str, role: str, content: str):
    conn = get_connection()
    conn.execute(
        "INSERT INTO messages (phone, role, content) VALUES (?, ?, ?)",
        (phone, role, content)
    )
    conn.commit()
    conn.close()


def get_conversation_history(phone: str, limit: int = 10) -> list[dict]:
    """
    Repo 3 pattern: rebuild conversation history from DB for LangGraph.
    Returns oldest-first so LLM sees correct temporal order.
    """
    conn = get_connection()
    rows = conn.execute(
        """SELECT role, content FROM messages
           WHERE phone = ? ORDER BY timestamp DESC LIMIT ?""",
        (phone, limit)
    ).fetchall()
    conn.close()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
