from datetime import timedelta

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt, get_jwt_identity

from decorators import role_required
from extensions import db
from models import Announcement, AnnouncementReadState
from time_utils import utc_now_naive


announcements_bp = Blueprint("announcements", __name__, url_prefix="/api/announcements")
ANNOUNCEMENT_TTL = timedelta(hours=24)
MAX_ANNOUNCEMENT_LENGTH = 4000


def _purge_expired_announcements():
    cutoff = utc_now_naive() - ANNOUNCEMENT_TTL
    deleted = Announcement.query.filter(Announcement.created_at < cutoff).delete(
        synchronize_session=False
    )
    if deleted:
        db.session.commit()


def _unread_count(last_read_id):
    cutoff = utc_now_naive() - ANNOUNCEMENT_TTL
    return Announcement.query.filter(
        Announcement.created_at >= cutoff,
        Announcement.id > last_read_id,
    ).count()


@announcements_bp.route("", methods=["GET"])
@role_required("teacher", "student")
def list_announcements():
    _purge_expired_announcements()
    role = get_jwt().get("role")
    announcements = Announcement.query.filter(
        Announcement.created_at >= utc_now_naive() - ANNOUNCEMENT_TTL
    ).order_by(Announcement.created_at.desc(), Announcement.id.desc()).all()

    unread_count = 0
    if role == "student":
        user_id = int(get_jwt_identity())
        read_state = AnnouncementReadState.query.filter_by(user_id=user_id).first()
        last_read_id = read_state.last_read_announcement_id if read_state else 0
        unread_count = _unread_count(last_read_id)

    return jsonify({
        "success": True,
        "announcements": [announcement.to_dict() for announcement in announcements],
        "unread_count": unread_count,
    }), 200


@announcements_bp.route("", methods=["POST"])
@role_required("teacher")
def create_announcement():
    _purge_expired_announcements()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"success": False, "message": "Dữ liệu thông báo không hợp lệ."}), 400

    content = data.get("content")
    if not isinstance(content, str) or not content.strip():
        return jsonify({"success": False, "message": "Vui lòng nhập nội dung thông báo."}), 400
    content = content.strip()
    if len(content) > MAX_ANNOUNCEMENT_LENGTH:
        return jsonify({
            "success": False,
            "message": f"Nội dung không được vượt quá {MAX_ANNOUNCEMENT_LENGTH} ký tự.",
        }), 400

    announcement = Announcement(content=content)
    db.session.add(announcement)
    db.session.commit()
    return jsonify({
        "success": True,
        "announcement": announcement.to_dict(),
    }), 201


@announcements_bp.route("/read", methods=["POST"])
@role_required("student")
def mark_announcements_read():
    _purge_expired_announcements()
    data = request.get_json(silent=True)
    through_id = data.get("through_id") if isinstance(data, dict) else None
    if isinstance(through_id, bool) or not isinstance(through_id, int) or through_id < 0:
        return jsonify({"success": False, "message": "Mốc thông báo đã đọc không hợp lệ."}), 400

    cutoff = utc_now_naive() - ANNOUNCEMENT_TTL
    latest_visible_id = db.session.query(db.func.max(Announcement.id)).filter(
        Announcement.id <= through_id,
        Announcement.created_at >= cutoff,
    ).scalar()
    user_id = int(get_jwt_identity())
    read_state = AnnouncementReadState.query.filter_by(user_id=user_id).first()
    if not read_state:
        read_state = AnnouncementReadState(
            user_id=user_id,
            last_read_announcement_id=0,
        )
        db.session.add(read_state)
    if latest_visible_id is not None:
        read_state.last_read_announcement_id = max(
            read_state.last_read_announcement_id,
            latest_visible_id,
        )
    db.session.commit()

    return jsonify({
        "success": True,
        "unread_count": _unread_count(read_state.last_read_announcement_id),
    }), 200


@announcements_bp.route("/<int:announcement_id>", methods=["DELETE"])
@role_required("teacher")
def delete_announcement(announcement_id):
    _purge_expired_announcements()
    announcement = db.session.get(Announcement, announcement_id)
    if not announcement:
        return jsonify({"success": False, "message": "Không tìm thấy thông báo."}), 404

    db.session.delete(announcement)
    db.session.commit()
    return jsonify({"success": True}), 200
