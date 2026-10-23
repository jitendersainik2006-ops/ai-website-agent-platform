"""Isolated In-Memory Database Mode for Black Intel AI Website Agent Platform.

Provides a 100% isolated, non-persistent, in-memory MongoDB environment using
mongomock. Ensures zero connection to MongoDB Atlas or any remote database,
preventing any production data contamination during local browser exploration
and testing.
"""

import logging
import os
from typing import Any

from flask import Flask

logger = logging.getLogger(__name__)

ISOLATED_ENV_VARS = (
    "ISOLATED_LOCAL_DB",
    "LOCAL_ISOLATED_DB",
    "MOCK_DB",
    "BLACK_INTEL_ISOLATED_DB",
)

TRUTHY_VALUES = {"1", "true", "yes", "on", "t"}


def is_isolated_db_enabled(config: dict | None = None) -> bool:
    """Return True if isolated in-memory database mode was explicitly requested."""
    if config and config.get("ISOLATED_LOCAL_DB") is not None:
        val = config.get("ISOLATED_LOCAL_DB")
        if isinstance(val, bool):
            return val
        return str(val).strip().lower() in TRUTHY_VALUES

    for env_var in ISOLATED_ENV_VARS:
        val = os.environ.get(env_var)
        if val is not None and val.strip().lower() in TRUTHY_VALUES:
            return True

    return False


def setup_isolated_db(app: Flask) -> tuple[Any, Any]:
    """Initialize an isolated in-memory mongomock database.

    Fails closed if mongomock is not available, completely redacting and
    ignoring the configured MONGODB_URI to guarantee zero production Atlas contact.
    """
    try:
        import mongomock
    except ImportError as exc:
        logger.critical(
            "ISOLATED DATABASE MODE FAILED: 'mongomock' is not available in the current environment. "
            "Failing closed to prevent connecting to production database."
        )
        raise RuntimeError(
            "ISOLATED DATABASE MODE FAILED: 'mongomock' is not installed in the environment. "
            "Failing closed to prevent connecting to production database."
        ) from exc

    # Explicitly overwrite MONGODB_URI in application config so no component can inspect or reuse Atlas URI
    app.config["MONGODB_URI"] = "mongomock://localhost/isolated_in_memory"
    app.config["ISOLATED_LOCAL_DB"] = True

    client = mongomock.MongoClient()
    db = client[app.config["MONGODB_DATABASE"]]

    banner = (
        "\n"
        + "=" * 74
        + "\n"
        + " DATABASE MODE: ISOLATED IN-MEMORY TEST DATABASE (mongomock)\n"
        + " - Remote MongoDB URI is completely ignored.\n"
        + " - Production MongoDB Atlas will NEVER be contacted.\n"
        + " - All test sessions, chat conversations, and records are ephemeral.\n"
        + " - Data exists strictly in memory and will reset when this process exits.\n"
        + "=" * 74
        + "\n"
    )
    logger.info("DATABASE MODE: ISOLATED IN-MEMORY TEST DATABASE (mongomock) enabled.")
    print(banner, flush=True)

    return client, db


def seed_isolated_db(db) -> dict:
    """Idempotently seed the isolated in-memory database with Black Intel demo data.

    Allows immediate, full-featured interactive testing of homepage chat,
    consultation booking, customer portal, and operator administration.
    """
    from app.security.passwords import hash_password
    from app.services.official_knowledge import OFFICIAL_BLACK_INTEL_KNOWLEDGE

    # 1. Primary Black Intel Demo Tenant
    db.tenants.update_one(
        {"slug": "black-intel-demo"},
        {
            "$set": {
                "name": "Black Intel Demo",
                "slug": "black-intel-demo",
                "status": "active",
            }
        },
        upsert=True,
    )
    tenant = db.tenants.find_one({"slug": "black-intel-demo"})
    tenant_id = tenant["_id"]

    # 2. Demo Admin User (for operator/control center access)
    db.users.update_one(
        {"email": "admin@blackintel.com"},
        {
            "$set": {
                "name": "Demo Admin",
                "email": "admin@blackintel.com",
                "password_hash": hash_password("ChangeMe123!"),
                "status": "active",
            }
        },
        upsert=True,
    )
    user = db.users.find_one({"email": "admin@blackintel.com"})
    user_id = user["_id"]

    # 3. Membership
    db.memberships.update_one(
        {"tenant_id": tenant_id, "user_id": user_id},
        {"$set": {"tenant_id": tenant_id, "user_id": user_id, "role": "owner", "status": "active"}},
        upsert=True,
    )

    # 4. Business Profile
    db.business_profiles.update_one(
        {"tenant_id": tenant_id},
        {
            "$set": {
                "name": "Black Intel",
                "description": (
                    "Black Intel Private Limited provides sovereign cybersecurity, digital forensics, "
                    "threat intelligence operations, and incident response consulting."
                ),
                "contact_email": "abhishek.managerr@gmail.com",
                "contact_phone": "+91 9205105369",
                "timezone": "Asia/Kolkata",
                "appointment_duration_minutes": 30,
                "appointment_buffer_minutes": 15,
            }
        },
        upsert=True,
    )

    # 5. Widget Config
    db.widget_configs.update_one(
        {"tenant_id": tenant_id},
        {
            "$set": {
                "tenant_id": tenant_id,
                "public_key": "demo_black_intel_widget_key",
                "enabled": True,
                "allowed_origins": [],
                "welcome_message": "Hello. I am the Black Intel AI assistant. How can I help you with our services, cybersecurity consultations, or general questions today?",
                "theme": {"accent": "#c5a059"},
            }
        },
        upsert=True,
    )

    # 6. Published Services
    services_to_seed = (
        ("Cyber Offense Command", "Proactive threat neutralization, adversary emulation, and advanced penetration testing."),
        ("Cybercrime & Digital Investigations", "Corporate cyber fraud investigations, internal misconduct probes, and evidence recovery."),
        ("Forensic Truth Extraction & Recovery", "Deep-level digital artifact extraction, deleted evidence recovery, and forensic timeline reconstruction."),
        ("Incident Response & Crisis Containment", "Rapid triage, ransomware mitigation, containment, and system recovery."),
    )
    for title, desc in services_to_seed:
        db.services.update_one(
            {"tenant_id": tenant_id, "title": title},
            {"$set": {"tenant_id": tenant_id, "title": title, "description": desc, "status": "published"}},
            upsert=True,
        )

    # 7. Published FAQs
    faqs_to_seed = (
        ("What services does Black Intel offer?", "Black Intel provides comprehensive cybersecurity, digital forensics, threat intelligence, cyber offense command, and incident response."),
        ("How do I book a consultation?", "Please use the consultation booking form on this website to choose a preferred date and time during business hours (Monday–Friday, 09:00–17:00 IST)."),
    )
    for q, a in faqs_to_seed:
        db.faqs.update_one(
            {"tenant_id": tenant_id, "question": q},
            {"$set": {"tenant_id": tenant_id, "question": q, "answer": a, "status": "published"}},
            upsert=True,
        )

    # 8. Business Hours (Monday to Friday, 09:00 to 17:00 IST)
    for weekday in range(5):
        db.business_hours.update_one(
            {"tenant_id": tenant_id, "weekday": weekday},
            {"$set": {"tenant_id": tenant_id, "weekday": weekday, "enabled": True, "start_time": "09:00", "end_time": "17:00"}},
            upsert=True,
        )

    # 9. Official Knowledge Records
    knowledge_count = 0
    for record in OFFICIAL_BLACK_INTEL_KNOWLEDGE:
        db.knowledge.update_one(
            {"tenant_id": tenant_id, "official_key": record["official_key"]},
            {"$set": {"tenant_id": tenant_id, **record, "status": "published"}},
            upsert=True,
        )
        knowledge_count += 1

    return {
        "tenant_id": str(tenant_id),
        "admin_email": "admin@blackintel.com",
        "widget_key": "demo_black_intel_widget_key",
        "knowledge_records": knowledge_count,
    }
