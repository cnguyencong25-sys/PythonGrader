"""
Quản lý phiên đăng nhập server-side.

CHÍNH SÁCH: SINGLE-SESSION
- Mỗi user chỉ có 1 phiên hoạt động tại 1 thời điểm.
- Login ở máy B -> session của máy A bị revoke NGAY.
- Máy A request kế tiếp -> before_request phát hiện -> đá về /login.
"""
import secrets
from datetime import timedelta
from extensions import db
from models import UserSession
from time_utils import utc_now_naive


# ============================================================
# CẤU HÌNH
# ============================================================
IDLE_TIMEOUT_MINUTES = 50
IDLE_CHECK_GRACE_MINUTES = 2


# ============================================================
# TẠO SESSION MỚI — SINGLE-SESSION: revoke hết session cũ
# ============================================================
def create_session(user_id: int, ip: str, user_agent: str) -> str:
    """
    1. Revoke TẤT CẢ session cũ của user (đá mọi máy khác ra).
    2. Tạo session mới.
    Trả về session_id mới.
    """
    # ---------- Revoke tất cả session cũ ----------
    now = utc_now_naive()
    old_sessions = UserSession.query.filter_by(
        user_id=user_id, is_revoked=False
    ).all()
    for s in old_sessions:
        s.is_revoked = True
        s.revoked_at = now
        s.revoked_reason = "another_login"   # đá do login nơi khác
    db.session.commit()

    # ---------- Tạo session mới ----------
    session_id = secrets.token_urlsafe(32)
    session = UserSession(
        session_id=session_id,
        user_id=user_id,
        ip_address=(ip or "")[:64],
        user_agent=(user_agent or "")[:255],
        last_activity=now,
        is_revoked=False,
    )
    db.session.add(session)
    db.session.commit()
    return session_id


# ============================================================
# KIỂM TRA SESSION (gọi ở mỗi request có auth)
# ============================================================
def verify_session(session_id: str) -> tuple[bool, str | None]:
    if not session_id:
        return False, "missing_session"

    session = UserSession.query.filter_by(session_id=session_id).first()
    if not session:
        return False, "session_not_found"

    if session.is_revoked:
        return False, f"revoked:{session.revoked_reason or 'unknown'}"

    # ---------- Tự kiểm tra idle ----------
    idle_limit = utc_now_naive() - timedelta(
        minutes=IDLE_TIMEOUT_MINUTES + IDLE_CHECK_GRACE_MINUTES
    )
    if session.last_activity < idle_limit:
        _revoke(session, "idle_timeout")
        return False, "idle_timeout"

    # ---------- Cập nhật last_activity ----------
    session.last_activity = utc_now_naive()
    db.session.commit()

    return True, None


# ============================================================
# REVOKE
# ============================================================
def _revoke(session: UserSession, reason: str):
    session.is_revoked = True
    session.revoked_at = utc_now_naive()
    session.revoked_reason = reason
    db.session.commit()


def revoke_session(session_id: str, reason: str = "logout") -> bool:
    session = UserSession.query.filter_by(session_id=session_id).first()
    if not session:
        return False
    _revoke(session, reason)
    return True


def revoke_all_for_user(user_id: int, except_session_id: str | None = None,
                        reason: str = "force_logout") -> int:
    q = UserSession.query.filter_by(user_id=user_id, is_revoked=False)
    if except_session_id:
        q = q.filter(UserSession.session_id != except_session_id)

    sessions = q.all()
    now = utc_now_naive()
    for s in sessions:
        s.is_revoked = True
        s.revoked_at = now
        s.revoked_reason = reason

    db.session.commit()
    return len(sessions)


# ============================================================
# ĐẾM / LIỆT KÊ SESSION (DÀNH CHO GV - sau này)
# ============================================================
def count_active_sessions(user_id: int, except_session_id: str | None = None) -> int:
    q = UserSession.query.filter_by(user_id=user_id, is_revoked=False)
    if except_session_id:
        q = q.filter(UserSession.session_id != except_session_id)

    idle_limit = utc_now_naive() - timedelta(minutes=IDLE_TIMEOUT_MINUTES)
    q = q.filter(UserSession.last_activity >= idle_limit)
    return q.count()


def list_active_sessions(user_id: int, except_session_id: str | None = None):
    idle_limit = utc_now_naive() - timedelta(minutes=IDLE_TIMEOUT_MINUTES)
    q = UserSession.query.filter(
        UserSession.user_id == user_id,
        UserSession.is_revoked == False,
        UserSession.last_activity >= idle_limit,
    )
    if except_session_id:
        q = q.filter(UserSession.session_id != except_session_id)
    return q.order_by(UserSession.last_activity.desc()).all()


def get_session_history(user_id: int, limit: int = 20):
    """
    Lịch sử phiên của 1 user (kể cả đã revoke).
    Dùng cho GV xem sau này.
    """
    return UserSession.query.filter_by(user_id=user_id) \
        .order_by(UserSession.created_at.desc()) \
        .limit(limit).all()