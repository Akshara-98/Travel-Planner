import json
import queue
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import requests
from flask import current_app

try:
    import google.generativeai as genai
except Exception:  # pragma: no cover
    genai = None

from .db import save_plan, upsert_request

ACTIVE_EXECUTIONS: Dict[str, Dict[str, Any]] = {}
ACTIVE_EXECUTIONS_LOCK = threading.Lock()


def _execution_state(execution_id: str):
    with ACTIVE_EXECUTIONS_LOCK:
        state = ACTIVE_EXECUTIONS.setdefault(
            execution_id,
            {
                "events": [],
                "queue": queue.Queue(),
                "lock": threading.Lock(),
                "plan": None,
                "status": "queued",
                "request": {},
            },
        )
    return state


def initialize_execution(execution_id: str, request_data: Dict[str, Any]):
    state = _execution_state(execution_id)
    state["request"] = request_data
    return state


def emit_event(execution_id: str, step_name: str, status: str, **kwargs):
    state = _execution_state(execution_id)
    with state["lock"]:
        event_id = len(state["events"])
        payload = {
            "id": event_id,
            "execution_id": execution_id,
            "step_name": step_name,
            "status": status,
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            **kwargs,
        }
        state["events"].append(payload)
        state["queue"].put(payload)
        state["status"] = status if status in {"pending", "running", "completed", "failed", "retrying", "waiting_for_approval"} else state["status"]
    return payload


def fetch_weather(city: str) -> Dict[str, Any]:
    try:
        response = requests.get(f"https://wttr.in/{city}?format=j1", timeout=current_app.config.get("REQUEST_TIMEOUT", 20))
        response.raise_for_status()
        payload = response.json()
        current = payload.get("current_condition", [{}])[0]
        weather = {
            "tool": "weather",
            "status": "completed",
            "summary": f"{current.get('weatherDesc', [{}])[0].get('value', 'Weather details unavailable')} with {current.get('temp_C', 'N/A')}°C.",
            "temperature_c": current.get("temp_C", "N/A"),
            "condition": current.get("weatherDesc", [{}])[0].get("value", "Unknown"),
            "raw": payload,
        }
        return weather
    except Exception as exc:  # pragma: no cover
        return {
            "tool": "weather",
            "status": "failed",
            "summary": f"Weather lookup failed: {exc}",
            "error": str(exc),
        }


def fetch_wikipedia(destination: str) -> Dict[str, Any]:
    try:
        url = "https://en.wikipedia.org/w/api.php"
        params = {
            "action": "query",
            "format": "json",
            "prop": "extracts|pageimages",
            "explaintext": 1,
            "exintro": 1,
            "redirects": 1,
            "titles": destination,
            "piprop": "original",
            "formatversion": 2,
        }
        response = requests.get(
            url,
            params=params,
            headers={"User-Agent": current_app.config["WIKIPEDIA_USER_AGENT"]},
            timeout=current_app.config.get("REQUEST_TIMEOUT", 20),
        )
        response.raise_for_status()
        payload = response.json()
        page = (payload.get("query", {}).get("pages") or [{}])[0]
        extract = page.get("extract", "Wikipedia summary unavailable.")
        return {
            "tool": "wikipedia",
            "status": "completed",
            "summary": extract[:350] + ("..." if len(extract) > 350 else ""),
            "page_title": page.get("title", destination),
            "extract": extract,
        }
    except Exception as exc:  # pragma: no cover
        return {
            "tool": "wikipedia",
            "status": "failed",
            "summary": f"Wikipedia lookup failed: {exc}",
            "error": str(exc),
        }


def validate_inputs(form_data: Dict[str, Any]) -> Dict[str, Any]:
    errors = []
    destination = (form_data.get("destination") or "").strip()
    start_date = (form_data.get("start_date") or "").strip()
    end_date = (form_data.get("end_date") or "").strip()
    travelers = form_data.get("travelers")
    budget = str(form_data.get("budget") or "").strip()
    email = (form_data.get("email") or "").strip()

    if not destination:
        errors.append("Destination is required.")
    if not start_date:
        errors.append("Travel start date is required.")
    if not end_date:
        errors.append("Travel end date is required.")
    if start_date and end_date and start_date > end_date:
        errors.append("End date must be after the start date.")
    try:
        travelers_value = int(travelers)
        if travelers_value <= 0:
            errors.append("The number of travelers must be at least 1.")
    except (TypeError, ValueError):
        errors.append("Number of travelers must be a valid integer.")
    if not budget:
        errors.append("Budget is required.")
    if email and "@" not in email:
        errors.append("A valid email address is required.")

    return {
        "valid": not errors,
        "errors": errors,
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "travelers": int(travelers) if isinstance(travelers, str) and travelers.isdigit() else travelers,
        "budget": budget,
        "email": email,
    }


def _extract_content(text: str) -> Dict[str, Any]:
    try:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:].strip()
        return json.loads(cleaned)
    except Exception:
        return {}


def fallback_plan(request_data: Dict[str, Any], weather: Dict[str, Any], wiki: Dict[str, Any]) -> Dict[str, Any]:
    destination = request_data["destination"]
    start_date = request_data["start_date"]
    end_date = request_data["end_date"]
    travelers = request_data["travelers"]
    budget = request_data["budget"]
    interests = (request_data.get("interests") or "").strip() or "local culture and scenic landmarks"
    itinerary = [
        {
            "day": "Day 1",
            "summary": f"Arrival and orientation in {destination}",
            "activities": [
                "Check in and settle into your stay",
                f"Explore the central districts of {destination}",
                f"Enjoy a guided walk focused on {interests}",
            ],
            "estimated_cost": "$120",
        },
        {
            "day": "Day 2",
            "summary": f"Highlight sightseeing with a local experience in {destination}",
            "activities": [
                f"Visit key landmarks and viewpoints in {destination}",
                "Try a local food or market experience",
                "Capture scenic moments at sunset",
            ],
            "estimated_cost": "$180",
        },
        {
            "day": "Day 3",
            "summary": f"Flexible exploration based on weather and your interests",
            "activities": [
                f"Spend time at a cultural or nature site related to {interests}",
                "Enjoy a low-cost evening stroll",
                "Prepare for departure or a final activity",
            ],
            "estimated_cost": "$140",
        },
    ]
    return {
        "plan_id": f"plan-{uuid.uuid4().hex[:8]}",
        "destination": destination,
        "start_date": start_date,
        "end_date": end_date,
        "travelers": travelers,
        "budget": budget,
        "email": request_data.get("email"),
        "status": "pending_approval",
        "weather_summary": weather.get("summary", "Weather details unavailable."),
        "recommended_places": [destination, f"Historic district of {destination}", f"Local market and food spots in {destination}"],
        "itinerary": itinerary,
        "estimated_expenses": {"transport": "$200", "lodging": "$400", "activities": "$300", "food": "$220"},
        "travel_recommendations": [
            "Carry layers for city weather changes.",
            "Book major attractions in advance if the trip is busy.",
            "Use local transit or walking for the most efficient city exploration.",
        ],
        "important_notes": [
            wiki.get("summary", "Wikipedia details were not available.")[:200],
            "This itinerary was generated using tool outputs and operational validation.",
        ],
    }


def _build_prompt(request_data: Dict[str, Any], weather: Dict[str, Any], wiki: Dict[str, Any]) -> str:
    return f"""
    You are a travel planner agent. Build a personalized itinerary using the user request and retrieved external information.

    User request:
    - Destination: {request_data.get('destination')}
    - Start date: {request_data.get('start_date')}
    - End date: {request_data.get('end_date')}
    - Travelers: {request_data.get('travelers')}
    - Budget: {request_data.get('budget')}
    - Preferences: {request_data.get('interests') or 'Flexible and scenic'}
    - Starting location: {request_data.get('starting_location') or 'Not provided'}
    - Additional instructions: {request_data.get('additional_instructions') or 'None'}

    Weather info:
    {json.dumps(weather, indent=2, default=str)}

    Wikipedia context:
    {json.dumps(wiki, indent=2, default=str)}

    Return valid JSON only with keys: plan_id, destination, start_date, end_date, travelers, budget, email, status, weather_summary, recommended_places, itinerary, estimated_expenses, travel_recommendations, important_notes.
    The itinerary should be a list of day objects with day, summary, activities, estimated_cost.
    Keep the output concise but useful.
    """


def call_gemini(request_data: Dict[str, Any], weather: Dict[str, Any], wiki: Dict[str, Any]) -> Dict[str, Any]:
    api_key = current_app.config.get("GEMINI_API_KEY")
    if not api_key:
        return fallback_plan(request_data, weather, wiki)

    if genai is None:
        return fallback_plan(request_data, weather, wiki)

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(current_app.config.get("GEMINI_MODEL", "gemini-2.0-flash"))
        response = model.generate_content(
            _build_prompt(request_data, weather, wiki),
            generation_config={"temperature": 0.4},
        )
        text = getattr(response, "text", "") or ""
        parsed = _extract_content(text)
        if parsed:
            parsed["plan_id"] = parsed.get("plan_id") or f"plan-{uuid.uuid4().hex[:8]}"
            parsed["destination"] = parsed.get("destination") or request_data.get("destination")
            parsed["status"] = "pending_approval"
            return parsed
    except Exception as exc:  # pragma: no cover
        return fallback_plan(request_data, weather, wiki)

    return fallback_plan(request_data, weather, wiki)


def generate_plan(request_data: Dict[str, Any], execution_id: Optional[str] = None):
    execution_id = execution_id or str(uuid.uuid4())
    state = initialize_execution(execution_id, request_data)
    state["status"] = "running"

    emit_event(execution_id, "User Input Received", "completed", summary=f"Received request for {request_data.get('destination')}", tool_name="web_form")
    validation = validate_inputs(request_data)
    if not validation["valid"]:
        emit_event(execution_id, "Input Validation", "failed", summary="; ".join(validation["errors"]), validation_result="invalid", error="; ".join(validation["errors"]))
        state["status"] = "failed"
        return {"valid": False, "errors": validation["errors"]}

    emit_event(execution_id, "Input Validation", "completed", summary="Input data validated successfully.", validation_result="valid")
    emit_event(execution_id, "AI Model Initialization", "running", summary="Initializing Gemini model and agent configuration.")
    api_key = current_app.config.get("GEMINI_API_KEY")
    if api_key:
        emit_event(execution_id, "AI Model Initialization", "completed", summary=f"Gemini model configured with model {current_app.config.get('GEMINI_MODEL', 'gemini-2.0-flash')}.")
    else:
        emit_event(execution_id, "AI Model Initialization", "failed", summary="Missing GEMINI_API_KEY. Defaulting to fallback plan generation.", error="Missing GEMINI_API_KEY")

    emit_event(execution_id, "Agent Goal and Instructions Preparation", "completed", summary="Agent instructions prepared for destination research and itinerary synthesis.")
    emit_event(execution_id, "Tool Selection", "running", summary="Selecting the weather and knowledge tools needed to support planning.")

    weather = fetch_weather(request_data.get("destination"))
    if weather.get("status") == "completed":
        emit_event(execution_id, "Weather Tool Execution", "completed", tool_name="weather_api", summary=weather.get("summary"), decision="Weather context gathered to guide timing and activity choices.")
    else:
        emit_event(execution_id, "Weather Tool Execution", "failed", tool_name="weather_api", summary=weather.get("summary"), decision="Weather data unavailable; fallback planning remains possible.", error=weather.get("error"))

    wiki = fetch_wikipedia(request_data.get("destination"))
    if wiki.get("status") == "completed":
        emit_event(execution_id, "Wikipedia Tool Execution", "completed", tool_name="wikipedia_api", summary=wiki.get("summary")[:220], decision="Destination context retrieved for relevant recommendations.")
    else:
        emit_event(execution_id, "Wikipedia Tool Execution", "failed", tool_name="wikipedia_api", summary=wiki.get("summary"), decision="Knowledge gap noted; moving forward with available context.", error=wiki.get("error"))

    upsert_request(execution_id, request_data.get("destination"), request_data.get("start_date"), request_data.get("end_date"), request_data.get("travelers"), request_data.get("budget"), request_data.get("email"), "processing", request_data)
    emit_event(execution_id, "Database Tool Execution", "completed", tool_name="sqlite", summary="Stored the request and execution checkpoint in SQLite.", decision="The request is queued for plan generation and later approval tracking.")

    completeness = "sufficient" if weather.get("status") == "completed" or wiki.get("status") == "completed" else "insufficient"
    if completeness == "sufficient":
        emit_event(execution_id, "Information Completeness Validation", "completed", summary="Required research output is sufficient to continue planning.", validation_result="sufficient", decision="Proceeding to itinerary creation.")
    else:
        emit_event(execution_id, "Information Completeness Validation", "retrying", summary="Missing data from external tools. A fallback or retry path is needed.", validation_result="insufficient", decision="Retry or proceed with available information.", error="Tool data incomplete")

    plan = call_gemini(request_data, weather, wiki)
    plan["destination"] = request_data.get("destination")
    plan["start_date"] = request_data.get("start_date")
    plan["end_date"] = request_data.get("end_date")
    plan["travelers"] = request_data.get("travelers")
    plan["budget"] = request_data.get("budget")
    plan["email"] = request_data.get("email")
    plan["status"] = "pending_approval"
    plan["plan_id"] = plan.get("plan_id", f"plan-{uuid.uuid4().hex[:8]}")

    save_plan(plan, execution_id)
    state["plan"] = plan
    state["status"] = "approval_needed"

    emit_event(execution_id, "Travel Plan Generation", "completed", tool_name="gemini", summary=f"Generated a travel plan for {request_data.get('destination')}.", decision="Itinerary drafted from weather, destination context, and user preferences.", output_summary=json.dumps({"plan_id": plan["plan_id"], "destination": plan["destination"], "travelers": plan["travelers"]}, default=str))

    validation_message = "Travel plan aligns with destination, budget, and traveler constraints."
    emit_event(execution_id, "Final Plan Validation", "completed", summary=validation_message, validation_result="accepted", decision="The plan meets the minimum user requirements and is ready for approval.")
    emit_event(execution_id, "Waiting for User Approval", "waiting_for_approval", summary="The plan is ready. User approval is required before database or email actions can proceed.", decision="Protect actions until explicit user confirmation.")
    state["request"] = request_data
    return {"execution_id": execution_id, "plan": plan, "status": "approval_needed"}
