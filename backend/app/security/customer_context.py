from functools import wraps

from flask import g, jsonify, request

from app.services.customer_service import get_customer_identity


def require_customer_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return jsonify({"error": "unauthorized", "message": "Customer authentication is required."}), 401
        identity = get_customer_identity(authorization.removeprefix("Bearer ").strip())
        if not identity:
            return jsonify({"error": "unauthorized", "message": "Customer authentication is required."}), 401
        g.customer_auth = identity
        return view(*args, **kwargs)

    return wrapped
