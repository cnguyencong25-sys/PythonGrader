import os
import re
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token, set_access_cookies, unset_jwt_cookies,
    jwt_required, get_jwt, get_jwt_identity
)
from extensions import db
from models import User, LoginLog
from session_manager import create_session, revoke_session, revoke_all_for_user
from decorators import role_required

auth_bp = Blueprint("auth", __name__, url_prefix="/api/auth")

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _json_error(msg: str, code: int = 400):
    return jsonify({"success": False, "message": msg}), code


def _client_ip() -> str:
    # Lấy IP thật (đi qua proxy thì dùng X-Forwarded-For)
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr or ""


def _client_ua() -> str:
    return (request.headers.get("User-Agent") or "")[:255]


def _log(email: str, user_id, success: bool, reason: str):
    try:
        db.session.add(LoginLog(
            email=email,
            user_id=user_id,
            success=success,
            reason=reason,
            ip_address=_client_ip()[:64],
            user_agent=_client_ua(),
        ))
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"[LOGIN LOG ERROR] {e}")


# ============================================================
# ĐĂNG NHẬP
# ============================================================
@auth_bp.route("/login", methods=["POST"])
def login():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return _json_error("Vui lòng nhập email và mật khẩu.")

    user = User.query.filter_by(email=email).first()

    if not user:
        _log(email, None, False, "no_user")
        return _json_error("Email hoặc mật khẩu không đúng.", 401)

    if not user.check_password(password):
        _log(email, user.id, False, "wrong_password")
        return _json_error("Email hoặc mật khẩu không đúng.", 401)

    # ---------- Login thành công ----------
    session_id = create_session(user.id, _client_ip(), _client_ua())

    token = create_access_token(
        identity=str(user.id),
        additional_claims={
            "role": user.role,
            "email": user.email,
            "sid": session_id,       # ⭐ session_id nhét vào JWT
        }
    )

    if user.role == "teacher":
        redirect_url = "/teacher/dashboard"
    elif not user.profile_completed:
        redirect_url = "/student/complete-profile"
    else:
        redirect_url = "/student/dashboard"

    _log(email, user.id, True, "success")

    resp = jsonify({
        "success": True,
        "user": user.to_dict(),
        "redirect": redirect_url,
    })
    set_access_cookies(resp, token)
    return resp, 200


# ============================================================
# ĐĂNG KÝ
# ============================================================
@auth_bp.route("/register", methods=["POST"])
def register():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    confirm = data.get("confirm_password") or ""

    if not EMAIL_REGEX.match(email):
        return _json_error("Email không hợp lệ.")
    if len(password) < 8:
        return _json_error("Mật khẩu phải có ít nhất 8 ký tự.")
    if len(password.encode("utf-8")) > 72:
        return _json_error("Mật khẩu không được vượt quá 72 byte.")
    if password != confirm:
        return _json_error("Mật khẩu xác nhận không khớp.")

    teacher_email = (os.getenv("TEACHER_EMAIL") or "").strip().lower()
    if teacher_email and email == teacher_email:
        return _json_error("Email này không được phép đăng ký.", 403)

    if User.query.filter_by(email=email).first():
        return _json_error("Email đã được sử dụng.", 409)

    user = User(email=email, role="student", profile_completed=False)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    session_id = create_session(user.id, _client_ip(), _client_ua())

    token = create_access_token(
        identity=str(user.id),
        additional_claims={
            "role": user.role,
            "email": user.email,
            "sid": session_id,
        }
    )

    _log(email, user.id, True, "register")

    resp = jsonify({
        "success": True,
        "user": user.to_dict(),
        "redirect": "/student/complete-profile",
    })
    set_access_cookies(resp, token)
    return resp, 201


# ============================================================
# HOÀN TẤT HỒ SƠ SV
# ============================================================
@auth_bp.route("/complete-profile", methods=["POST"])
@jwt_required()
def complete_profile():
    claims = get_jwt()
    if claims.get("role") != "student":
        return _json_error("Chỉ sinh viên mới cần hoàn tất hồ sơ.", 403)

    data = request.get_json(silent=True) or {}
    full_name  = (data.get("full_name")  or "").strip()
    class_name = (data.get("class_name") or "").strip()
    student_id = (data.get("student_id") or "").strip()

    if not full_name or not class_name or not student_id:
        return _json_error("Vui lòng nhập đầy đủ họ tên, lớp và MSV.")
    if len(full_name) < 2 or len(full_name) > 100:
        return _json_error("Họ tên phải từ 2 đến 100 ký tự.")
    if len(class_name) > 50:
        return _json_error("Tên lớp quá dài (tối đa 50 ký tự).")
    if len(student_id) > 50:
        return _json_error("Mã sinh viên quá dài (tối đa 50 ký tự).")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", student_id):
        return _json_error("MSV chỉ được chứa chữ, số, gạch ngang hoặc gạch dưới.")

    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return _json_error("Không tìm thấy người dùng.", 404)

    dup = User.query.filter(User.student_id == student_id, User.id != user.id).first()
    if dup:
        return _json_error("MSV này đã được đăng ký bởi tài khoản khác.", 409)

    user.full_name  = full_name
    user.class_name = class_name
    user.student_id = student_id
    user.profile_completed = True
    db.session.commit()

    return jsonify({
        "success": True,
        "user": user.to_dict(),
        "redirect": "/student/dashboard"
    }), 200


# ============================================================
# THÔNG TIN USER HIỆN TẠI
# ============================================================
@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def me():
    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return _json_error("Không tìm thấy người dùng.", 404)
    return jsonify({"success": True, "user": user.to_dict()}), 200


@auth_bp.route("/student-profile", methods=["PUT"])
@role_required("student")
def update_student_profile():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu hồ sơ không hợp lệ.")

    full_name = data.get("full_name")
    student_id = data.get("student_id")
    class_name = data.get("class_name")
    if not all(isinstance(value, str) for value in (full_name, student_id, class_name)):
        return _json_error("Vui lòng nhập đầy đủ họ tên, MSV và lớp.")

    full_name = full_name.strip()
    student_id = student_id.strip()
    class_name = class_name.strip()
    if not full_name or not student_id or not class_name:
        return _json_error("Vui lòng nhập đầy đủ họ tên, MSV và lớp.")
    if len(full_name) < 2 or len(full_name) > 100:
        return _json_error("Họ tên phải từ 2 đến 100 ký tự.")
    if len(class_name) > 50:
        return _json_error("Tên lớp tối đa 50 ký tự.")
    if len(student_id) > 50 or not re.fullmatch(r"[A-Za-z0-9_-]+", student_id):
        return _json_error("MSV tối đa 50 ký tự và chỉ gồm chữ, số, gạch ngang hoặc gạch dưới.")

    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return _json_error("Không tìm thấy sinh viên.", 404)

    duplicate = User.query.filter(
        User.student_id == student_id,
        User.id != user.id,
    ).first()
    if duplicate:
        return _json_error("MSV này đã được đăng ký bởi tài khoản khác.", 409)

    user.full_name = full_name
    user.student_id = student_id
    user.class_name = class_name
    user.profile_completed = True
    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Đã cập nhật thông tin cá nhân.",
        "user": user.to_dict(),
    }), 200


@auth_bp.route("/change-password", methods=["POST"])
@role_required("student")
def change_student_password():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu đổi mật khẩu không hợp lệ.")

    current_password = data.get("current_password")
    new_password = data.get("new_password")
    confirm_password = data.get("confirm_password")
    if not all(isinstance(value, str) for value in (
        current_password, new_password, confirm_password
    )):
        return _json_error("Vui lòng nhập đầy đủ ba trường mật khẩu.")
    if not current_password or not new_password or not confirm_password:
        return _json_error("Vui lòng nhập đầy đủ ba trường mật khẩu.")
    if new_password != confirm_password:
        return _json_error("Mật khẩu mới và xác nhận mật khẩu không khớp.")
    if len(new_password) < 8:
        return _json_error("Mật khẩu mới phải có ít nhất 8 ký tự.")
    if not new_password.strip():
        return _json_error("Mật khẩu mới không được chỉ chứa khoảng trắng.")
    if len(new_password.encode("utf-8")) > 72:
        return _json_error("Mật khẩu mới không được vượt quá 72 byte.")

    user = User.query.get(int(get_jwt_identity()))
    if not user:
        return _json_error("Không tìm thấy sinh viên.", 404)
    if not user.check_password(current_password):
        return _json_error("Mật khẩu hiện tại không chính xác.", 400)

    user.set_password(new_password)
    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Đã đổi mật khẩu thành công.",
    }), 200


# ============================================================
# HEARTBEAT — frontend gọi mỗi 5 phút khi user còn tương tác
# ============================================================
@auth_bp.route("/ping", methods=["POST"])
@jwt_required()
def ping():
    # Chỉ cần @jwt_required + before_request hook đã cập nhật last_activity
    return jsonify({"success": True}), 200


# ============================================================
# ĐĂNG XUẤT (chỉ session hiện tại)
# ============================================================
@auth_bp.route("/logout", methods=["POST"])
@jwt_required(optional=True)
def logout():
    claims = get_jwt()
    sid = claims.get("sid") if claims else None
    user_id = get_jwt_identity()

    if sid:
        revoke_session(sid, reason="logout")
        if user_id:
            _log(claims.get("email", ""), int(user_id), True, "logout")

    resp = jsonify({"success": True, "message": "Đã đăng xuất."})
    unset_jwt_cookies(resp)
    return resp, 200


# ============================================================
# ⭐ FORCE LOGOUT — đăng xuất TẤT CẢ thiết bị khác
# ============================================================
@auth_bp.route("/logout-all", methods=["POST"])
@jwt_required()
def logout_all():
    claims = get_jwt()
    user_id = int(get_jwt_identity())
    current_sid = claims.get("sid")

    n = revoke_all_for_user(user_id, except_session_id=current_sid,
                            reason="force_logout")

    _log(claims.get("email", ""), user_id, True,
         f"force_logout:{n}_sessions")

    return jsonify({
        "success": True,
        "message": f"Đã đăng xuất {n} thiết bị khác.",
        "revoked_count": n,
    }), 200