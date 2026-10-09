from pathlib import Path
from urllib.parse import urlsplit

from flask import Flask, request

from .config import Config
from .db import init_db
from .routes import main_bp

BASE_DIR = Path(__file__).resolve().parent.parent


def create_app():
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "templates"),
        static_folder=str(BASE_DIR / "static"),
    )
    app.config.from_object(Config)

    init_db(app.config["DB_PATH"])

    @app.after_request
    def allow_live_server_api(response):
        origin = request.headers.get("Origin")
        if origin:
            parsed_origin = urlsplit(origin)
            if parsed_origin.scheme == "http" and parsed_origin.hostname in {"localhost", "127.0.0.1"}:
                response.headers["Access-Control-Allow-Origin"] = origin
                response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
                response.headers["Access-Control-Allow-Headers"] = "Content-Type, Last-Event-ID"
                response.vary.add("Origin")
        return response

    app.register_blueprint(main_bp)
    return app
