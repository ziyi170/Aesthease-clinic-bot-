"""
Admin API routes — protected by a simple token header.
All data comes from the same clinic.db SQLite database.

Endpoints:
  GET /admin/stats           → summary counts
  GET /admin/patients        → all patients
  GET /admin/appointments    → all appointments (with filters)
  GET /admin/messages/{phone}→ conversation history for one patient
  PUT /admin/appointments/{id}/cancel → cancel an appointment
"""
import os
from fastapi import APIRouter, HTTPException, Header
from src.shared.db import get_connection

router = APIRouter(prefix="/admin", tags=["admin"])

ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "aesthease-admin-2026")


def require_auth(x_admin_token: str = Header(None)):
    if x_admin_token != ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid admin token")


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
def get_stats(x_admin_token: str = Header(None)):
    require_auth(x_admin_token)
    conn = get_connection()
    stats = {
        "total_patients":     conn.execute("SELECT COUNT(*) FROM patients").fetchone()[0],
        "total_appointments": conn.execute("SELECT COUNT(*) FROM appointments WHERE status='confirmed'").fetchone()[0],
        "cancelled":          conn.execute("SELECT COUNT(*) FROM appointments WHERE status='cancelled'").fetchone()[0],
        "total_messages":     conn.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0],
        "channels": {
            "whatsapp":  conn.execute("SELECT COUNT(*) FROM patients WHERE phone NOT LIKE 'fb_%' AND phone NOT LIKE 'ig_%'").fetchone()[0],
            "messenger": conn.execute("SELECT COUNT(*) FROM patients WHERE phone LIKE 'fb_%'").fetchone()[0],
            "instagram": conn.execute("SELECT COUNT(*) FROM patients WHERE phone LIKE 'ig_%'").fetchone()[0],
        }
    }
    conn.close()
    return stats


# ── Patients ──────────────────────────────────────────────────────────────────

@router.get("/patients")
def get_patients(x_admin_token: str = Header(None)):
    require_auth(x_admin_token)
    conn = get_connection()
    rows = conn.execute("""
        SELECT p.*, 
               COUNT(CASE WHEN a.status='confirmed' THEN 1 END) as upcoming_appointments,
               COUNT(m.id) as total_messages
        FROM patients p
        LEFT JOIN appointments a ON p.phone = a.patient_phone
        LEFT JOIN messages m ON p.phone = m.phone AND m.role = 'user'
        GROUP BY p.id
        ORDER BY p.created_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Appointments ──────────────────────────────────────────────────────────────

@router.get("/appointments")
def get_appointments(status: str = "all", x_admin_token: str = Header(None)):
    require_auth(x_admin_token)
    conn = get_connection()
    if status == "all":
        rows = conn.execute("SELECT * FROM appointments ORDER BY datetime_str DESC").fetchall()
    else:
        rows = conn.execute("SELECT * FROM appointments WHERE status=? ORDER BY datetime_str DESC", (status,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.put("/appointments/{appt_id}/cancel")
def cancel_appt(appt_id: int, x_admin_token: str = Header(None)):
    require_auth(x_admin_token)
    conn = get_connection()
    conn.execute("UPDATE appointments SET status='cancelled' WHERE id=?", (appt_id,))
    conn.commit()
    conn.close()
    return {"success": True, "id": appt_id}


# ── Messages ──────────────────────────────────────────────────────────────────

@router.get("/messages/{phone}")
def get_messages(phone: str, x_admin_token: str = Header(None)):
    require_auth(x_admin_token)
    conn = get_connection()
    rows = conn.execute(
        "SELECT role, content, timestamp FROM messages WHERE phone=? ORDER BY timestamp ASC",
        (phone,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


@router.get("/conversation-phones")
def get_conversation_phones(x_admin_token: str = Header(None)):
    require_auth(x_admin_token)
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT phone FROM messages ORDER BY phone"
    ).fetchall()
    conn.close()
    return [{"phone": r["phone"]} for r in rows]
