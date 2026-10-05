import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, jsonify
from pymongo import MongoClient


def create_app(config: dict | None = None, mongo_client=None) -> Flask:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")

    app = Flask(__name__)
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

    from app.api.auth import auth_bp

    app.register_blueprint(auth_bp)

    @app.get("/api/v1/health")
    def health():
        try:
            app.extensions["mongo_client"].admin.command("ping")
        except Exception:
            return jsonify({"status": "unavailable"}), 503
        return jsonify({"status": "ok"})

    return app
