"""
Google Calendar tools for the agent.
Handles: check availability, create event, delete event.
"""
import os
import json
from datetime import datetime, timedelta
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ["https://www.googleapis.com/auth/calendar"]
CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")


def _get_calendar_service():
    creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if not creds_json:
        raise ValueError("GOOGLE_CREDENTIALS_JSON environment variable not set.")
    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=SCOPES
    )
    return build("calendar", "v3", credentials=creds)


def check_availability(date_str: str) -> list[dict]:
    """
    Return a list of free time slots for a given date.
    date_str format: "2026-07-01"
    Returns: [{"start": "2026-07-01 09:00", "end": "2026-07-01 10:00"}, ...]
    """
    service = _get_calendar_service()

    # Build time range for the full day
    day_start = datetime.strptime(date_str, "%Y-%m-%d").replace(hour=9, minute=0)
    day_end = day_start.replace(hour=18, minute=0)

    events_result = service.events().list(
        calendarId=CALENDAR_ID,
        timeMin=day_start.isoformat() + "Z",
        timeMax=day_end.isoformat() + "Z",
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    booked = events_result.get("items", [])
    booked_slots = set()
    for event in booked:
        start = event["start"].get("dateTime", "")
        if start:
            hour = datetime.fromisoformat(start.replace("Z", "")).hour
            booked_slots.add(hour)

    # Return 1-hour free slots from 9am to 6pm
    free_slots = []
    current = day_start
    while current < day_end:
        if current.hour not in booked_slots:
            free_slots.append({
                "start": current.strftime("%Y-%m-%d %H:%M"),
                "end": (current + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
            })
        current += timedelta(hours=1)

    return free_slots


def create_appointment_event(
    patient_name: str,
    service: str,
    datetime_str: str,
    patient_phone: str
) -> str:
    """
    Create a Google Calendar event.
    Returns the event ID.
    datetime_str format: "2026-07-01 14:00"
    """
    service_obj = _get_calendar_service()

    start_dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
    end_dt = start_dt + timedelta(hours=1)

    event = {
        "summary": f"[AesthEase] {patient_name} — {service}",
        "description": f"Patient: {patient_name}\nPhone: {patient_phone}\nService: {service}",
        "start": {"dateTime": start_dt.isoformat(), "timeZone": "Europe/London"},
        "end": {"dateTime": end_dt.isoformat(), "timeZone": "Europe/London"},
    }

    created = service_obj.events().insert(calendarId=CALENDAR_ID, body=event).execute()
    return created.get("id", "")


def delete_appointment_event(event_id: str) -> bool:
    """Delete a Google Calendar event by ID."""
    service = _get_calendar_service()
    service.events().delete(calendarId=CALENDAR_ID, eventId=event_id).execute()
    return True
