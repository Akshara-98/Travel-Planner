<<<<<<< HEAD
# Agentic AI Travel Planner

A Flask-based travel planner that shows its agent workflow in a live execution timeline. The app collects and validates trip details, researches weather and destination information, generates an itinerary with Gemini (or a fallback plan), waits for user approval, and can save the approved plan to SQLite or send it via SMTP.

## Features

- Responsive Bootstrap 5 frontend
- Real-time backend execution events via server-sent events (SSE)
- Gemini integration for itinerary generation
- Weather and Wikipedia research
- SQLite persistence for plans and planning requests
- Human approval workflow for revisions, approval, and rejection
- Optional email delivery of approved plans
- Single-file frontend in the root `index.html`

## Setup and run with Flask

From the project root in PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
.\.venv\Scripts\python.exe app.py
```

If you do not have a virtual environment yet, create one first:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Open <http://127.0.0.1:5000> after the server starts. If `.env` already exists, do not overwrite it with the example; configure the needed values there instead.

## Run with VS Code Live Server

1. Start the Flask backend from the project root with `.\.venv\Scripts\python.exe app.py` and leave it running on port 5000.
2. In VS Code, right-click the root `index.html` and choose **Open with Live Server**.
3. Live Server hosts the static frontend; it does not run the Python backend. The page sends API requests and its event stream to `http://127.0.0.1:5000`.

The Bootstrap stylesheet is loaded from jsDelivr, so an internet connection is required for the existing Bootstrap layout.

## Configuration

See `.env.example` for the available environment variables. Set `GEMINI_API_KEY` to enable Gemini itinerary generation. Without it, the application uses its fallback planner. Configure the SMTP variables to enable email delivery. Set `WIKIPEDIA_USER_AGENT` to an identifiable application name and contact address to follow Wikipedia's API etiquette.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

An email address is optional when generating a plan. The interface enables save and email actions after approval; email also requires an address.
=======
# travel_project
>>>>>>> 1dc23fcb4bc4113be8ef7dc6cdec6aa2b6f37780
