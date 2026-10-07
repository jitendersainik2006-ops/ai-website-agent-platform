from pymongo import ReturnDocument

from app import create_app
from app.security.passwords import hash_password


app = create_app()


def seed() -> None:
    with app.app_context():
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
