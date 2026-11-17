from functools import wraps
from flask import jsonify
from flask_jwt_extended import jwt_required, get_jwt


def role_required(*allowed_roles):
    def wrapper(fn):
        @wraps(fn)
        @jwt_required()
        def decorated(*args, **kwargs):
            claims = get_jwt()
            if claims.get("role") not in allowed_roles:
                return jsonify({
                    "success": False,
                    "message": "Bạn không có quyền truy cập chức năng này."
                }), 403
            return fn(*args, **kwargs)
        return decorated
    return wrapper