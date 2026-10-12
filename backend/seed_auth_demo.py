from pymongo import ReturnDocument

from app import create_app
from app.security.passwords import hash_password


app = create_app()


OFFICIAL_BLACK_INTEL_KNOWLEDGE = (
    {
        "official_key": "company-overview-2026",
        "title": "What Black Intel does",
        "content": (
            "Black Intel describes itself as a sovereign digital power unit combining cybersecurity, "
            "artificial intelligence, digital forensics, and counter-intelligence. Its official site says "
            "the company was founded to address the gap between advanced threats and intelligent defense."
        ),
        "source_url": "https://theblackintel.com/",
    },
    {
        "official_key": "core-services-2026",
        "title": "What services does Black Intel offer?",
        "content": (
            "Black Intel's official site lists Digital Forensics, Cyber Offense, and Defensive Security as "
            "core divisions. Published capabilities include disk and memory forensics, mobile data extraction, "
            "deep and dark web tracking, penetration operations, red teaming, SIEM and SOC operations, threat "
            "detection, and cloud and network security."
        ),
        "source_url": "https://theblackintel.com/",
    },
    {
        "official_key": "client-consultations-2026",
        "title": "How does Black Intel work with clients?",
        "content": (
            "Black Intel invites prospective clients to request a consultation to discuss their needs. The "
            "official site does not publish a fixed engagement process, so a consultation is the approved "
            "next step for confirming the right scope."
        ),
        "source_url": "https://theblackintel.com/contact",
    },
    {
        "official_key": "legal-service-scope-2026",
        "title": "Black Intel service scope",
        "content": (
            "Black Intel states that its cybersecurity, digital forensics, and intelligence analysis services "
            "operate within applicable national and international laws and are defensive, investigative, and "
            "advisory in nature."
        ),
        "source_url": "https://theblackintel.com/",
    },
)


def seed() -> None:
    with app.app_context():
        uri = app.config["MONGODB_URI"].lower()
        if not (uri.startswith("mongodb://localhost") or uri.startswith("mongodb://127.0.0.1")):
            raise RuntimeError("Demo seeding is restricted to a local MongoDB instance. It will not modify a remote database.")
        db = app.extensions["mongo_db"]

        tenant = db.tenants.find_one_and_update(
            {"slug": "black-intel-demo"},
            {
                "$set": {
                    "name": "Black Intel Demo",
                    "slug": "black-intel-demo",
                    "status": "active",
                }
            },
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

        user = db.users.find_one_and_update(
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
            return_document=ReturnDocument.AFTER,
        )

        db.memberships.update_one(
            {"tenant_id": tenant["_id"], "user_id": user["_id"]},
            {
                "$set": {
                    "tenant_id": tenant["_id"],
                    "user_id": user["_id"],
                    "role": "owner",
                    "status": "active",
                }
            },
            upsert=True,
        )

        db.business_profiles.update_one(
            {"tenant_id": tenant["_id"]},
            {
                "$set": {
                    "name": "Black Intel Demo",
                    "description": "Black Intel Demo provides practical cybersecurity assessments, incident response guidance, and security consulting.",
                    "contact_email": "admin@blackintel.com",
                    "contact_phone": "+91 00000 00000",
                    "timezone": "Asia/Kolkata",
                    "appointment_duration_minutes": 30,
                    "appointment_buffer_minutes": 15,
                }
            },
            upsert=True,
        )
        db.widget_configs.update_one(
            {"tenant_id": tenant["_id"]},
            {
                "$set": {
                    "tenant_id": tenant["_id"],
                    "public_key": "demo_black_intel_widget_key",
                    "enabled": True,
                    "allowed_origins": [],
                    "welcome_message": "Welcome to Black Intel Demo. How can we help?",
                    "theme": {"accent": "#28c7b7"},
                }
            },
            upsert=True,
        )
        db.services.update_one(
            {"tenant_id": tenant["_id"], "title": "Security Assessment"},
            {"$set": {"tenant_id": tenant["_id"], "title": "Security Assessment", "description": "A focused assessment of security controls and priority risks.", "status": "published"}},
            upsert=True,
        )
        db.faqs.update_one(
            {"tenant_id": tenant["_id"], "question": "What services do you provide?"},
            {"$set": {"tenant_id": tenant["_id"], "question": "What services do you provide?", "answer": "We provide security assessments, incident response guidance, and security consulting.", "status": "published"}},
            upsert=True,
        )
        for item in OFFICIAL_BLACK_INTEL_KNOWLEDGE:
            db.knowledge.update_one(
                {"tenant_id": tenant["_id"], "official_key": item["official_key"]},
                {"$set": {"tenant_id": tenant["_id"], **item, "status": "published"}},
                upsert=True,
            )
        for weekday in range(5):
            db.business_hours.update_one(
                {"tenant_id": tenant["_id"], "weekday": weekday},
                {"$set": {"tenant_id": tenant["_id"], "weekday": weekday, "enabled": True, "start_time": "09:00", "end_time": "17:00"}},
                upsert=True,
            )

        print("Demo admin created: admin@blackintel.com")
        print("Demo widget key: demo_black_intel_widget_key")


if __name__ == "__main__":
    seed()
