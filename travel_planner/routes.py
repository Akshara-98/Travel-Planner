import json
import threading
import uuid
from pathlib import Path

from flask import Blueprint, Response, current_app, jsonify, request, send_from_directory

from .agent import ACTIVE_EXECUTIONS, emit_event, generate_plan, initialize_execution
from .db import save_plan, update_plan_status
from .email_service import send_plan_email

main_bp = Blueprint("main", __name__)
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)


@main_bp.route("/")
def index():
    return send_from_directory(PROJECT_ROOT, "index.html")


@main_bp.route("/health")
def health():
    return jsonify({"status": "ok"})


@main_bp.route("/api/travel-plan", methods=["POST"])
def submit_planning_request():
    payload = request.form.to_dict() if request.form else request.get_json(silent=True) or {}
    destination = (payload.get("destination") or "").strip()
    start_date = (payload.get("start_date") or "").strip()
    end_date = (payload.get("end_date") or "").strip()
    email = (payload.get("email") or "").strip()
    payload["email"] = email

    if not destination or not start_date or not end_date:
        return jsonify({"error": "Destination and travel dates are required."}), 400

    execution_id = payload.get("execution_id") or f"exec-{uuid.uuid4().hex}"
    initialize_execution(execution_id, payload)
    emit_event(
        execution_id,
        "Plan Request Accepted",
        "running",
        summary="Your travel request was accepted. Planning is starting.",
    )
    app = current_app._get_current_object()

    def worker():
        with app.app_context():
            try:
                generate_plan(payload, execution_id)
            except Exception:
                app.logger.exception("Travel plan generation failed for execution %s", execution_id)
                emit_event(
                    execution_id,
                    "Travel Plan Generation",
                    "failed",
                    summary="Plan generation failed due to a server error. Check the application logs.",
                    error="See application logs for details.",
                )

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"execution_id": execution_id, "status": "started"})


@main_bp.route("/api/events/<execution_id>")
def stream_events(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state:
        return jsonify({"error": "Execution not found."}), 404

    last_id = request.args.get("last_event_id", default=None, type=int)

    def generate():
        with state["lock"]:
            events = list(state.get("events", []))
        if last_id is not None:
            events = events[last_id + 1 :]
        last_sent_id = last_id if last_id is not None else -1
        for event in events:
            yield f"id: {event['id']}\ndata: {json.dumps(event)}\n\n"
            last_sent_id = event["id"]
        while True:
            item = state["queue"].get()
            if item is None:
                break
            if item["id"] <= last_sent_id:
                continue
            yield f"id: {item['id']}\ndata: {json.dumps(item)}\n\n"
            last_sent_id = item["id"]

    return Response(generate(), mimetype="text/event-stream")


@main_bp.route("/api/plans/<execution_id>", methods=["GET"])
def get_plan_state(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state:
        return jsonify({"error": "Execution not found."}), 404
    return jsonify({"status": state.get("status"), "plan": state.get("plan")})


@main_bp.route("/api/plans/<execution_id>/approve", methods=["POST"])
def approve_plan(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state or not state.get("plan"):
        return jsonify({"error": "No plan is available for approval."}), 404

    plan = state["plan"]
    plan["status"] = "approved"
    emit_event(execution_id, "User Approval", "completed", summary="User approved the plan. Protected actions can proceed.", decision="Approved")
    state["status"] = "approved"
    save_plan(plan, execution_id)
    return jsonify({"status": "approved", "plan": plan})


@main_bp.route("/api/plans/<execution_id>/reject", methods=["POST"])
def reject_plan(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state or not state.get("plan"):
        return jsonify({"error": "No plan is available to reject."}), 404
    plan = state["plan"]
    plan["status"] = "rejected"
    state["status"] = "rejected"
    emit_event(execution_id, "User Rejection", "completed", summary="User rejected the plan.", decision="No database or email actions will be executed.")
    return jsonify({"status": "rejected", "plan": plan})


@main_bp.route("/api/plans/<execution_id>/revise", methods=["POST"])
def revise_plan(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state or not state.get("request"):
        return jsonify({"error": "No active execution for revision."}), 404
    request_data = dict(state["request"])
    feedback = (request.get_json(silent=True) or {}).get("feedback", "")
    if feedback:
        request_data["additional_instructions"] = feedback

    emit_event(execution_id, "Plan Revision Requested", "running", summary="User requested plan improvements.", decision=f"Requested revisions: {feedback or 'General refinement'}")
    app = current_app._get_current_object()

    def worker():
        with app.app_context():
            generate_plan(request_data, execution_id)

    threading.Thread(target=worker, daemon=True).start()
    return jsonify({"status": "revision_started", "execution_id": execution_id})


@main_bp.route("/api/plans/<execution_id>/save", methods=["POST"])
def save_approved_plan(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state or not state.get("plan"):
        return jsonify({"error": "Plan not found or not approved yet."}), 404
    plan = state["plan"]
    if plan.get("status") not in {"approved", "pending_approval"}:
        return jsonify({"error": "Plan must be approved before it can be saved."}), 400
    saved_id = save_plan(plan, execution_id)
    update_plan_status(saved_id, "saved")
    return jsonify({"status": "saved", "plan_id": saved_id, "message": "Approved travel plan saved to SQLite."})


@main_bp.route("/api/plans/<execution_id>/email", methods=["POST"])
def email_approved_plan(execution_id):
    state = ACTIVE_EXECUTIONS.get(execution_id)
    if not state or not state.get("plan"):
        return jsonify({"error": "Plan not found or not approved yet."}), 404
    plan = state["plan"]
    if plan.get("status") != "approved":
        return jsonify({"error": "Only approved plans can be emailed."}), 400
    if not plan.get("email"):
        return jsonify({"error": "Add an email address before sending the approved plan."}), 400
    try:
        result = send_plan_email(plan, plan.get("email"))
        return jsonify({"status": "email_sent", "result": result})
    except Exception as exc:  # pragma: no cover
        return jsonify({"status": "email_failed", "error": str(exc)}), 400
