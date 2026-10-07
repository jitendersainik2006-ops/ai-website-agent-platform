from functools import wraps

from flask import g, jsonify


def require_roles(*roles):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if getattr(g, "auth", {}).get("role") not in roles:
                return jsonify({"error": "forbidden", "message": "You do not have permission for this action."}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator
