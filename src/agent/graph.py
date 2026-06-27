"""
LangGraph agent — AesthEase Clinic Bot.

Repo 2 patterns applied:
  - Pydantic validators on tool inputs (ReservationTimeModel, DateModel)
  - "one tool at a time" rule in system prompt
  - JSONLoader-style FAQ query

Repo 3 patterns applied:
  - Conversation history rebuilt from DB (consume_messages pattern)
"""
import os
from typing import TypedDict, Annotated
from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage, ToolMessage
from langchain_core.tools import tool

from src.shared.db import (
    get_patient, create_patient, get_appointments_by_phone,
    create_appointment, cancel_appointment, save_message, get_conversation_history
)
from src.shared.rag import query_faq
from src.shared.models import Patient, Appointment, ReservationTimeModel, DateModel
from src.mcp_server.calendar_tools import (
    check_availability, create_appointment_event, delete_appointment_event
)

# ── State ──────────────────────────────────────────────────────────────────────

class ClinicState(TypedDict):
    messages: Annotated[list, add_messages]
    phone: str
    patient_name: str
    intent: str

# ── Tools ──────────────────────────────────────────────────────────────────────

@tool
def search_faq(question: str) -> str:
    """Search the clinic knowledge base to answer patient questions about services, prices, and policies."""
    result = query_faq(question)
    return result if result else "I don't have specific information about that. Please call us directly or ask our staff."


@tool
def get_available_slots(date_str: str) -> str:
    """
    Check available appointment slots for a given date.
    Input must be a date string in format YYYY-MM-DD, e.g. '2026-07-01'.
    """
    # Repo 2: Pydantic validation before hitting Calendar API
    try:
        validated = DateModel(date_str=date_str)
    except ValueError as e:
        return str(e)

    slots = check_availability(validated.date_str)
    if not slots:
        return f"No available slots on {date_str}. Please try another date."
    lines = [f"• {s['start']} – {s['end']}" for s in slots]
    return f"Available slots on {date_str}:\n" + "\n".join(lines)


@tool
def book_appointment(patient_phone: str, patient_name: str, service: str, datetime_str: str) -> str:
    """
    Book an appointment for a patient.
    datetime_str must be in format 'YYYY-MM-DD HH:MM', e.g. '2026-07-01 14:00'.
    service: the treatment name, e.g. '水光针', 'Laser Treatment', 'Botox'.
    """
    # Repo 2: Pydantic validation before hitting Calendar API
    try:
        validated = ReservationTimeModel(datetime_str=datetime_str)
    except ValueError as e:
        return str(e)

    event_id = create_appointment_event(patient_name, service, validated.datetime_str, patient_phone)
    appt = Appointment(
        patient_phone=patient_phone,
        patient_name=patient_name,
        service=service,
        datetime_str=validated.datetime_str,
        google_event_id=event_id,
        status="confirmed"
    )
    create_appointment(appt)
    return f"✓ Appointment confirmed: {patient_name} — {service} on {validated.datetime_str}."


@tool
def list_patient_appointments(patient_phone: str) -> str:
    """List all upcoming confirmed appointments for a patient."""
    appts = get_appointments_by_phone(patient_phone)
    if not appts:
        return "You have no upcoming appointments."
    lines = [f"• #{a.id}: {a.service} on {a.datetime_str}" for a in appts]
    return "Your upcoming appointments:\n" + "\n".join(lines)


@tool
def cancel_patient_appointment(appointment_id: int, google_event_id: str) -> str:
    """Cancel an appointment by its ID. Requires the appointment ID number."""
    cancel_appointment(appointment_id)
    if google_event_id:
        try:
            delete_appointment_event(google_event_id)
        except Exception:
            pass
    return f"✓ Appointment #{appointment_id} has been cancelled."


@tool
def register_patient(phone: str, name: str, age: int) -> str:
    """Register a new patient. Call this when a patient contacts us for the first time."""
    existing = get_patient(phone)
    if existing:
        return f"Patient already registered as {existing.name}."
    create_patient(Patient(phone=phone, name=name, age=age))
    return f"✓ Welcome, {name}! You are now registered with AesthEase Clinic."


TOOLS = [
    search_faq,
    get_available_slots,
    book_appointment,
    list_patient_appointments,
    cancel_patient_appointment,
    register_patient,
]

# ── LLM ───────────────────────────────────────────────────────────────────────

llm = ChatOpenAI(
    model="gpt-4o-mini",
    temperature=0.3,
    api_key=os.getenv("OPENAI_API_KEY")
).bind_tools(TOOLS)

# ── System prompt (Repo 2: "one tool at a time" rule) ─────────────────────────

SYSTEM_PROMPT = """You are the AI receptionist for AesthEase Clinic, a premium medical aesthetics clinic.

Your responsibilities:
1. Answer questions about services, prices, and policies using the search_faq tool.
2. Help patients book, view, or cancel appointments using the calendar tools.
3. Register new patients when they contact us for the first time.

IMPORTANT RULES:
- Call only ONE tool at a time. Wait for its result before deciding next steps.
- Always check if a patient is registered before booking. If not, collect name and age first, then register.
- When booking, always check availability first, then confirm the slot with the patient before calling book_appointment.
- If you do not know something, say so honestly and offer to connect them with a human staff member.
- Never make up prices or medical advice not found in the knowledge base.
- Always reply in the same language the patient uses.
- Be warm, professional, and concise.
"""

# ── Graph nodes ────────────────────────────────────────────────────────────────

def agent_node(state: ClinicState) -> ClinicState:
    system = SystemMessage(content=SYSTEM_PROMPT)
    response = llm.invoke([system] + state["messages"])
    return {"messages": [response]}


def tools_node(state: ClinicState) -> ClinicState:
    tool_map = {t.name: t for t in TOOLS}
    last = state["messages"][-1]
    results = []
    for call in last.tool_calls:
        fn = tool_map.get(call["name"])
        result = fn.invoke(call["args"]) if fn else "Tool not found."
        results.append(ToolMessage(content=str(result), tool_call_id=call["id"]))
    return {"messages": results}


def should_use_tools(state: ClinicState) -> str:
    last = state["messages"][-1]
    if hasattr(last, "tool_calls") and last.tool_calls:
        return "tools"
    return END

# ── Build graph ────────────────────────────────────────────────────────────────

def build_graph():
    g = StateGraph(ClinicState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_use_tools, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()


GRAPH = build_graph()

# ── Public interface ───────────────────────────────────────────────────────────

def process_message(phone: str, user_text: str, channel: str = "whatsapp") -> str:
    """
    Entry point called by FastAPI webhook handlers.
    Repo 3 pattern: rebuild conversation history from DB (consume_messages).
    """
    # Rebuild history from DB → LangChain message objects
    raw_history = get_conversation_history(phone, limit=10)
    lc_history = []
    for msg in raw_history:
        if msg["role"] == "user":
            lc_history.append(HumanMessage(content=msg["content"]))
        else:
            lc_history.append(AIMessage(content=msg["content"]))
    lc_history.append(HumanMessage(content=user_text))

    result = GRAPH.invoke({
        "messages": lc_history,
        "phone": phone,
        "patient_name": "",
        "intent": "",
    })

    reply = result["messages"][-1].content

    save_message(phone, "user", user_text)
    save_message(phone, "assistant", reply)

    return reply
