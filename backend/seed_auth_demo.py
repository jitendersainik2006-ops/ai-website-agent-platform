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

        print("Demo admin created: admin@blackintel.com")


if __name__ == "__main__":
    seed()
