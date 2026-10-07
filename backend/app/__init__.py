import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify, send_from_directory
from pymongo import MongoClient


def create_app(config: dict | None = None, mongo_client=None) -> Flask:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    app = Flask(__name__, static_folder=str(frontend_dir), static_url_path="/frontend")
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        JWT_SECRET_KEY=os.environ.get("JWT_SECRET_KEY"),
        JWT_EXPIRY_MINUTES=int(os.environ.get("JWT_EXPIRY_MINUTES", "30")),
        MONGODB_URI=os.environ.get("MONGODB_URI", "mongodb://localhost:27017"),
        MONGODB_DATABASE=os.environ.get("MONGODB_DATABASE", "ai_agent_platform"),
    )
    if config:
        app.config.update(config)

    required_settings = ("SECRET_KEY", "JWT_SECRET_KEY")
    missing_settings = [name for name in required_settings if not app.config.get(name)]
    if missing_settings:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing_settings)
        )

    mongo_client = mongo_client or MongoClient(app.config["MONGODB_URI"])
    app.extensions["mongo_client"] = mongo_client
    app.extensions["mongo_db"] = mongo_client[app.config["MONGODB_DATABASE"]]
    from app.services.calendar_adapter import LocalCalendarAdapter
    from app.services.notifications import LocalNotificationProvider

    app.extensions["calendar_adapter"] = LocalCalendarAdapter()
    app.extensions["notification_provider"] = LocalNotificationProvider()
    _create_indexes(app.extensions["mongo_db"])

    from app.api.auth import auth_bp
    from app.api.admin import admin_bp
    from app.api.public import public_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)

    @app.after_request
    def security_headers(response):
        """Baseline browser protections that remain compatible with embed iframes."""
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response

    @app.get("/")
    def dashboard():
        return send_from_directory(frontend_dir / "admin", "index.html")

    @app.get("/widget-loader.js")
    def widget_loader():
        return send_from_directory(frontend_dir / "widget", "widget-loader.js", mimetype="application/javascript")

    @app.get("/widget-frame.html")
    def widget_frame():
        return send_from_directory(frontend_dir / "widget", "widget-frame.html")

    @app.get("/api/v1/health")
    def health():
        try:
            app.extensions["mongo_client"].admin.command("ping")
        except Exception:
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ok"})

    return app


def _create_indexes(db) -> None:
    db.tenants.create_index("slug", unique=True)
    db.users.create_index("email", unique=True)
    db.memberships.create_index([("tenant_id", 1), ("user_id", 1)], unique=True)
    db.widget_configs.create_index("public_key", unique=True, sparse=True)
    for collection in ("business_profiles", "services", "faqs", "knowledge", "business_hours", "blocked_times", "conversations", "messages", "leads", "appointments", "audit_logs"):
        db[collection].create_index("tenant_id")
    db.leads.create_index([("tenant_id", 1), ("email", 1)])
    db.appointments.create_index([("tenant_id", 1), ("start_at", 1)], unique=True)
