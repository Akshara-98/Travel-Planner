import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "travel-planner-dev-secret")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    DB_PATH = os.getenv("DATABASE_PATH", str(BASE_DIR / "travel_planner.db"))
    SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    SMTP_SENDER = os.getenv("SMTP_SENDER", "")
    REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "20"))
    WIKIPEDIA_USER_AGENT = os.getenv(
        "WIKIPEDIA_USER_AGENT",
        "AgenticAITravelPlanner/1.0 (Flask travel planner)",
    )
