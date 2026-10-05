from flask import Blueprint, jsonify, request
from pydantic import ValidationError

from app.schemas.auth import LoginRequest
from app.services.auth_service import get_authenticated_identity, login

auth_bp = Blueprint("auth", __name__, url_prefix="/api/v1/auth")

INVALID_CREDENTIALS = {
    "error": "invalid_credentials",
    "message": "Invalid email, password, or tenant.",
}


@auth_bp.post("/login")
def login_route():
    try:
        payload = LoginRequest.model_validate(request.get_json(silent=True) or {})
    except ValidationError:
        return jsonify(
            {
                "error": "validation_error",
                "message": "Please provide a valid email, password, and tenant slug.",
            }
        ), 400

    result = login(payload.email, payload.password, payload.tenant_slug)
    if not result:
        return jsonify(INVALID_CREDENTIALS), 401

    return jsonify(result), 200


@auth_bp.get("/me")
def me_route():
    authorization = request.headers.get("Authorization", "")
    if not authorization.startswith("Bearer "):
        return jsonify({"error": "unauthorized", "message": "Authentication is required."}), 401

    identity = get_authenticated_identity(authorization.removeprefix("Bearer ").strip())
    if not identity:
        return jsonify({"error": "unauthorized", "message": "Authentication is required."}), 401

    return jsonify(identity), 200
