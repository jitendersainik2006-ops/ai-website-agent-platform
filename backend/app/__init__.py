import logging
import os
from pathlib import Path
import re

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
        MONGODB_SERVER_SELECTION_TIMEOUT_MS=int(
            os.environ.get("MONGODB_SERVER_SELECTION_TIMEOUT_MS", "5000")
        ),
        LLM_PROVIDER=os.environ.get("LLM_PROVIDER", "local").lower(),
        GEMINI_API_KEY=os.environ.get("GEMINI_API_KEY", ""),
        GEMINI_MODEL=os.environ.get("GEMINI_MODEL", "gemini-3.8-flash"),
        GROQ_API_KEY=os.environ.get("GROQ_API_KEY", ""),
        GROQ_MODEL=os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
        OPENAI_COMPATIBLE_API_KEY=os.environ.get("OPENAI_COMPATIBLE_API_KEY", ""),
        OPENAI_COMPATIBLE_BASE_URL=os.environ.get("OPENAI_COMPATIBLE_BASE_URL", "https://api.groq.com/openai/v1"),
        OPENAI_COMPATIBLE_MODEL=os.environ.get("OPENAI_COMPATIBLE_MODEL", "llama-3.3-70b-versatile"),
        LLM_REQUEST_TIMEOUT_SECONDS=int(os.environ.get("LLM_REQUEST_TIMEOUT_SECONDS", "10")),
        WEB_SEARCH_ENABLED=os.environ.get("WEB_SEARCH_ENABLED", "false").lower() == "true",
    )
    if config:
        app.config.update(config)

    if app.config.get("TESTING") and (not config or "LLM_PROVIDER" not in config):
        app.config["LLM_PROVIDER"] = "local"

    required_settings = ("SECRET_KEY", "JWT_SECRET_KEY")
    missing_settings = [name for name in required_settings if not app.config.get(name)]
    if missing_settings:
        raise RuntimeError(
            "Missing required environment variables: " + ", ".join(missing_settings)
        )

    from app.isolated_db import is_isolated_db_enabled, setup_isolated_db, seed_isolated_db

    if mongo_client is not None:
        app.extensions["mongo_client"] = mongo_client
        app.extensions["mongo_db"] = mongo_client[app.config["MONGODB_DATABASE"]]
        app.extensions["is_isolated_db"] = type(mongo_client).__module__.startswith("mongomock")
    elif is_isolated_db_enabled(app.config):
        mongo_client, mongo_db = setup_isolated_db(app)
        app.extensions["mongo_client"] = mongo_client
        app.extensions["mongo_db"] = mongo_db
        app.extensions["is_isolated_db"] = True
        should_seed = app.config.get("SEED_DEMO_DATA")
        if should_seed is None:
            should_seed = not app.config.get("TESTING")
        if should_seed:
            seed_isolated_db(mongo_db)
    else:
        mongo_client = MongoClient(
            app.config["MONGODB_URI"],
            serverSelectionTimeoutMS=app.config["MONGODB_SERVER_SELECTION_TIMEOUT_MS"],
        )
        app.extensions["mongo_client"] = mongo_client
        app.extensions["mongo_db"] = mongo_client[app.config["MONGODB_DATABASE"]]
        app.extensions["is_isolated_db"] = False
        logger.info("DATABASE MODE: CONFIGURED DATABASE (remote/local MongoDB URI)")
    from app.services.calendar_adapter import LocalCalendarAdapter
    from app.services.notifications import LocalNotificationProvider

    app.extensions["calendar_adapter"] = LocalCalendarAdapter()
    app.extensions["notification_provider"] = LocalNotificationProvider()
    _create_indexes(app.extensions["mongo_db"])

    from app.api.auth import auth_bp
    from app.api.admin import admin_bp
    from app.api.public import public_bp
    from app.api.customer import customer_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(customer_bp)

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

    @app.get("/favicon.ico")
    @app.get("/black-intel-logo.png")
    def favicon():
        return send_from_directory(frontend_dir / "admin", "black-intel-logo.png", mimetype="image/png")

    @app.get("/api/v1/health")
    def health():
        try:
            app.extensions["mongo_client"].admin.command("ping")
        except Exception:
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ok"})

    return app


logger = logging.getLogger(__name__)


def _sanitize_index_error(exc: Exception) -> str:
    """Safely redact connection strings, credentials, or sensitive tokens from error messages."""
    msg = str(exc)
    msg = re.sub(r"://[^@]+@", "://[REDACTED]@", msg)
    msg = re.sub(r"mongodb(?:\+srv)?://[^\s\"']+", "[REDACTED_MONGODB_URI]", msg)
    msg = re.sub(r"key=[^\s&\"']+", "key=[REDACTED]", msg)
    return msg[:300]


def _create_indexes(db) -> None:
    def _safe_create_index(collection, *args, **kwargs):
        try:
            collection.create_index(*args, **kwargs)
        except Exception as exc:
            coll_name = getattr(collection, "name", str(collection))
            logger.warning(
                "Non-fatal index creation warning on collection '%s': %s",
                coll_name,
                _sanitize_index_error(exc),
            )

    _safe_create_index(db.tenants, "slug", unique=True)
    _safe_create_index(db.users, "email", unique=True)
    _safe_create_index(db.memberships, [("tenant_id", 1), ("user_id", 1)], unique=True)
    _safe_create_index(db.widget_configs, "public_key", unique=True, sparse=True)
    _safe_create_index(db.customers, [("tenant_id", 1), ("customer_id", 1)], unique=True)
    _safe_create_index(db.customers, [("tenant_id", 1), ("full_name_normalized", 1)])
    _safe_create_index(db.conversations, [("tenant_id", 1), ("customer_id", 1), ("updated_at", -1)])
    _safe_create_index(db.appointments, [("tenant_id", 1), ("customer_id", 1), ("start_at", -1)])
    for collection in ("business_profiles", "services", "faqs", "knowledge", "business_hours", "blocked_times", "conversations", "messages", "leads", "appointments", "audit_logs"):
        _safe_create_index(db[collection], "tenant_id")
    _safe_create_index(db.leads, [("tenant_id", 1), ("email", 1)])

    # Appointments start_at conflict-prevention index:
    # 1. Inspect existing indexes without assuming absence upon inspection failure.
    inspection_failed = False
    existing_indexes = {}
    try:
        existing_indexes = db.appointments.index_information()
    except Exception as exc:
        inspection_failed = True
        logger.warning(
            "Could not inspect existing appointment indexes (%s). Skipping index creation to preserve existing database state.",
            _sanitize_index_error(exc),
        )

    if inspection_failed:
        # If we cannot inspect existing indexes, do not attempt to guess or create.
        # Application-level availability checks and booking validation in scheduling_service
        # strictly enforce non-overlapping appointment intervals.
        return

    # Check whether an index on [("tenant_id", 1), ("start_at", 1)] already exists
    # (covers the legacy unique index on Atlas: tenant_id_1_start_at_1).
    matching_info = None
    for name, info in existing_indexes.items():
        if isinstance(info, dict) and list(info.get("key", [])) == [("tenant_id", 1), ("start_at", 1)]:
            matching_info = (name, info)
            break
    if not matching_info and "tenant_id_1_start_at_1" in existing_indexes:
        matching_info = ("tenant_id_1_start_at_1", existing_indexes["tenant_id_1_start_at_1"])

    if matching_info:
        idx_name, idx_spec = matching_info
        if isinstance(idx_spec, dict) and idx_spec.get("unique") is True:
            # Existing legacy or partial unique index already protects this key.
            # Preserve it intact without modifying options or dropping.
            return
        else:
            # Existing index is non-unique. We must never drop or alter it without approval,
            # and we do not attempt to modify it. Log explicit notice.
            logger.warning(
                "Existing index '%s' on appointments (tenant_id, start_at) is non-unique; preserving existing index without modification.",
                idx_name,
            )
            return

    # No existing index for [("tenant_id", 1), ("start_at", 1)] found.
    # Attempt to create the preferred partial unique index; if partial filter expressions
    # are unsupported, fall back to standard unique index.
    # Never downgrade to non-unique.
    try:
        db.appointments.create_index(
            [("tenant_id", 1), ("start_at", 1)],
            unique=True,
            partialFilterExpression={"status": {"$in": ["confirmed", "pending", "rescheduled"]}},
        )
    except Exception as exc:
        logger.warning(
            "Could not create partial unique index on appointments: %s. Attempting standard unique index.",
            _sanitize_index_error(exc),
        )
        try:
            db.appointments.create_index([("tenant_id", 1), ("start_at", 1)], unique=True)
        except Exception as exc2:
            logger.warning(
                "Could not establish unique index on appointments: %s. Safe continuation allowed as application-level scheduling checks enforce conflict prevention.",
                _sanitize_index_error(exc2),
            )
