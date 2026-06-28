import os
from dotenv import load_dotenv
load_dotenv()

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

llm_base = ChatOpenAI(
    model="openai/gpt-4o-mini",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    temperature=0.3,
)

class ClinicState(TypedDict):
    messages: Annotated[list, add_messages]
    phone: str
    patient_name: str
    intent: str

@tool
def search_faq(question: str) -> str:
    """Search the clinic knowledge base to answer patient questions about services, prices, and policies."""
    result = query_faq(question)
    return result if result else "I don't have specific information about that. Please call us directly."

@tool
def get_available_slots(date_str: str) -> str:
    """Check available appointment slots. Input format: YYYY-MM-DD e.g. 2026-07-01"""
    try:
        validated = DateModel(date_str=date_str)
    except ValueError as e:
        return str(e)
    slots = check_availability(validated.date_str)
    if not slots:
        return f"No available slots on {date_str}."
    lines = [f"• {s['start']} – {s['end']}" for s in slots]
    return f"Available slots on {date_str}:\n" + "\n".join(lines)

@tool
def book_appointment(patient_phone: str, patient_name: str, service: str, datetime_str: str) -> str:
    """
    Book an appointment. 
    patient_phone: must be the session ID (starts with web_ or 44...), NEVER the patient name.
    datetime_str format: YYYY-MM-DD HH:MM
    """
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
    return f"Appointment confirmed: {patient_name} — {service} on {validated.datetime_str}."

@tool
def list_patient_appointments(patient_phone: str) -> str:
    """List upcoming appointments. patient_phone must be the session ID."""
    appts = get_appointments_by_phone(patient_phone)
    if not appts:
        return "No upcoming appointments."
    lines = [f"• #{a.id}: {a.service} on {a.datetime_str}" for a in appts]
    return "Your upcoming appointments:\n" + "\n".join(lines)

@tool
def cancel_patient_appointment(appointment_id: int, google_event_id: str) -> str:
    """Cancel an appointment by ID."""
    cancel_appointment(appointment_id)
    if google_event_id:
        try:
            delete_appointment_event(google_event_id)
        except Exception:
            pass
    return f"Appointment #{appointment_id} cancelled."

@tool
def register_patient(phone: str, name: str, age: int) -> str:
    """
    Register a new patient.
    phone: must be the session ID (starts with web_ or 44...), NEVER the patient name.
    """
    existing = get_patient(phone)
    if existing:
        return f"Already registered as {existing.name}."
    create_patient(Patient(phone=phone, name=name, age=age))
    return f"Welcome, {name}! You are now registered."

TOOLS = [
    search_faq,
    get_available_slots,
    book_appointment,
    list_patient_appointments,
    cancel_patient_appointment,
    register_patient,
]

llm = llm_base.bind_tools(TOOLS)

def get_system_prompt(phone: str) -> str:
    return f"""You are the AI receptionist for AesthEase Clinic, a premium medical aesthetics clinic.

CRITICAL: The current patient's session ID is "{phone}".
You MUST use "{phone}" as the patient_phone parameter in ALL tool calls.
NEVER use the patient's name as patient_phone. Always use "{phone}".

Your responsibilities:
1. Answer questions about services, prices, and policies using search_faq.
2. Help patients book, view, or cancel appointments using calendar tools.
3. Register new patients when they contact us for the first time.

RULES:
- Call only ONE tool at a time.
- Always check if patient is registered before booking. If not, collect name and age first.
- Always check availability before booking.
- patient_phone in ALL tools = "{phone}" always.
- Reply in the same language the patient uses.
- Be warm, professional, and concise.
"""

def agent_node(state: ClinicState) -> ClinicState:
    system = SystemMessage(content=get_system_prompt(state["phone"]))
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

def build_graph():
    g = StateGraph(ClinicState)
    g.add_node("agent", agent_node)
    g.add_node("tools", tools_node)
    g.set_entry_point("agent")
    g.add_conditional_edges("agent", should_use_tools, {"tools": "tools", END: END})
    g.add_edge("tools", "agent")
    return g.compile()

GRAPH = build_graph()

def process_message(phone: str, user_text: str, channel: str = "whatsapp") -> str:
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
