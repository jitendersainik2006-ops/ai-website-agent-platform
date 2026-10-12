from datetime import datetime, timedelta, timezone

import jwt
from flask import current_app


def create_access_token(user_id: str, tenant_id: str, role: str) -> str:
    return _create_token(user_id, tenant_id, role)


def create_customer_access_token(customer_id: str, tenant_id: str) -> str:
    return _create_token(customer_id, tenant_id, "customer", subject_type="customer")


def _create_token(subject_id: str, tenant_id: str, role: str, subject_type: str | None = None) -> str:
    expiry = datetime.now(timezone.utc) + timedelta(
        minutes=current_app.config["JWT_EXPIRY_MINUTES"]
    )
    return jwt.encode(
        {
            "sub": subject_id,
            "tenant_id": tenant_id,
            "role": role,
            "exp": expiry,
            **({"subject_type": subject_type} if subject_type else {}),
        },
        current_app.config["JWT_SECRET_KEY"],
        algorithm="HS256",
    )


def decode_access_token(token: str) -> dict | None:
    try:
        return jwt.decode(
            token,
            current_app.config["JWT_SECRET_KEY"],
            algorithms=["HS256"],
        )
    except jwt.PyJWTError:
        return None
