from functools import wraps

from flask import g, jsonify, request

from app.services.auth_service import get_authenticated_identity


def require_auth(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return jsonify({"error": "unauthorized", "message": "Authentication is required."}), 401
        identity = get_authenticated_identity(authorization.removeprefix("Bearer ").strip())
        if not identity:
            return jsonify({"error": "unauthorized", "message": "Authentication is required."}), 401
        g.auth = identity
        request._cached_auth = identity
        return view(*args, **kwargs)

    return wrapped
