"""
Pydantic models — data models + tool parameter validators (Repo 2 pattern).
Repo 2 used DateTimeModel / DateModel validators for tool inputs.
We rename them to match our clinic context.
"""
from pydantic import BaseModel, field_validator
from typing import Optional
from datetime import datetime


# ── Database models ───────────────────────────────────────────────────────────

class Patient(BaseModel):
    id: Optional[int] = None
    phone: str
    name: str
    age: Optional[int] = None
    created_at: Optional[datetime] = None


class Appointment(BaseModel):
    id: Optional[int] = None
    patient_phone: str
    patient_name: str
    service: str
    datetime_str: str
    google_event_id: Optional[str] = None
    status: str = "confirmed"


class Message(BaseModel):
    id: Optional[int] = None
    phone: str
    role: str
    content: str
    timestamp: Optional[datetime] = None


# ── Tool parameter validators (Repo 2: DateTimeModel / DateModel pattern) ─────

class ReservationTimeModel(BaseModel):
    """
    Validates appointment datetime input from the agent.
    Repo 2 used this pattern to catch malformed dates before hitting the Calendar API.
    """
    datetime_str: str  # Expected: "YYYY-MM-DD HH:MM"

    @field_validator("datetime_str")
    @classmethod
    def validate_datetime(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d %H:%M")
        except ValueError:
            raise ValueError(
                f"Invalid datetime format: '{v}'. Expected 'YYYY-MM-DD HH:MM', e.g. '2026-07-01 14:00'"
            )
        return v


class DateModel(BaseModel):
    """Validates date-only input (for availability checks)."""
    date_str: str  # Expected: "YYYY-MM-DD"

    @field_validator("date_str")
    @classmethod
    def validate_date(cls, v: str) -> str:
        try:
            datetime.strptime(v, "%Y-%m-%d")
        except ValueError:
            raise ValueError(
                f"Invalid date format: '{v}'. Expected 'YYYY-MM-DD', e.g. '2026-07-01'"
            )
        return v


# ── WhatsApp incoming message ─────────────────────────────────────────────────

class IncomingWhatsAppMessage(BaseModel):
    phone: str
    message_text: str
    message_id: str
