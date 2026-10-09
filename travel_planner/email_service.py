import smtplib
from email.message import EmailMessage

from flask import current_app


def send_plan_email(plan: dict, recipient: str):
    smtp_server = current_app.config.get("SMTP_SERVER")
    smtp_port = current_app.config.get("SMTP_PORT", 587)
    username = current_app.config.get("SMTP_USERNAME")
    password = current_app.config.get("SMTP_PASSWORD")
    sender = current_app.config.get("SMTP_SENDER") or username

    if not all([smtp_server, username, password, sender, recipient]):
        raise RuntimeError("SMTP configuration is incomplete. Set SMTP_SERVER, SMTP_USERNAME, SMTP_PASSWORD, and SMTP_SENDER in the environment.")

    msg = EmailMessage()
    msg["Subject"] = f"Approved Travel Plan: {plan.get('destination', 'Trip')}"
    msg["From"] = sender
    msg["To"] = recipient

    body = [
        f"Travel Plan for {plan.get('destination', 'your trip')}",
        "",
        f"Dates: {plan.get('start_date')} to {plan.get('end_date')}",
        f"Travelers: {plan.get('travelers')}",
        f"Budget: {plan.get('budget')}",
        "",
        "Itinerary:",
    ]

    for day in plan.get("itinerary", []):
        body.append(f"- {day.get('day', 'Day')} : {day.get('summary', '')}")

    msg.set_content("\n".join(body))

    with smtplib.SMTP(smtp_server, smtp_port) as server:
        server.starttls()
        server.login(username, password)
        server.send_message(msg)

    return {
        "status": "accepted",
        "recipient": recipient,
        "subject": msg["Subject"],
        "message": "Your approved travel plan has been successfully submitted to the email service for delivery.",
    }
