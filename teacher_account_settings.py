from flask import Blueprint, jsonify, redirect, render_template, request
from flask_jwt_extended import get_jwt, get_jwt_identity, jwt_required

from decorators import role_required
from models import User
from system_settings import (
    REGISTRATION_BLOCKED,
    STUDENT_LOGIN_MAINTENANCE,
    is_setting_enabled,
    set_setting_enabled,
)


teacher_account_settings_bp = Blueprint(
    "teacher_account_settings",
    __name__,
)

SETTING_KEYS = {
    REGISTRATION_BLOCKED,
    STUDENT_LOGIN_MAINTENANCE,
}


@teacher_account_settings_bp.route("/teacher/accounts")
@jwt_required()
def teacher_account_settings_page():
    if get_jwt().get("role") != "teacher":
        return redirect("/student/dashboard")
    teacher = User.query.filter_by(
        id=int(get_jwt_identity()),
        role="teacher",
    ).first()
    if not teacher:
        return redirect("/login")
    return render_template(
        "teacher_accounts.html",
        user=teacher,
        active_tab="accounts",
    )


@teacher_account_settings_bp.route(
    "/api/teacher/account-settings",
    methods=["GET"],
)
@role_required("teacher")
def get_account_settings():
    return jsonify({
        "success": True,
        "settings": {
            key: is_setting_enabled(key)
            for key in sorted(SETTING_KEYS)
        },
    }), 200


@teacher_account_settings_bp.route(
    "/api/teacher/account-settings",
    methods=["PUT"],
)
@role_required("teacher")
def update_account_setting():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "message": "Dữ liệu cấu hình không hợp lệ.",
        }), 400

    key = data.get("key")
    enabled = data.get("enabled")
    if key not in SETTING_KEYS or type(enabled) is not bool:
        return jsonify({
            "success": False,
            "message": "Tùy chọn tài khoản không hợp lệ.",
        }), 400

    set_setting_enabled(key, enabled)
    return jsonify({
        "success": True,
        "key": key,
        "enabled": enabled,
    }), 200
