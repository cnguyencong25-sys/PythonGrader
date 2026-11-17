from flask import Blueprint, jsonify
from flask_jwt_extended import get_jwt_identity

from decorators import role_required
from extensions import db
from models import (
    ChapterSession,
    Exam,
    ExamRetakePermission,
    ExamSession,
    LoginLog,
    User,
    UserSession,
)
from time_utils import (
    utc_iso,
    utc_now_naive,
    vietnam_elapsed_seconds,
    vietnam_iso,
    vietnam_now_naive,
)


teacher_students_bp = Blueprint(
    "teacher_students", __name__, url_prefix="/api/teacher/students"
)


def _json_error(message, status=400):
    return jsonify({"success": False, "message": message}), status


@teacher_students_bp.route("", methods=["GET"])
@role_required("teacher")
def list_students():
    students = User.query.filter_by(role="student").order_by(
        User.full_name.asc(), User.student_id.asc(), User.id.asc()
    ).all()
    return jsonify({
        "success": True,
        "students": [{
            "id": student.id,
            "student_id": student.student_id or "",
            "full_name": student.full_name or "",
            "class_name": student.class_name or "",
            "email": student.email,
            "profile_completed": student.profile_completed,
        } for student in students],
    }), 200


@teacher_students_bp.route("/<int:student_user_id>/exam-history", methods=["GET"])
@role_required("teacher")
def student_exam_history(student_user_id):
    teacher_id = int(get_jwt_identity())
    student = User.query.filter_by(id=student_user_id, role="student").first()
    if not student:
        return _json_error("Không tìm thấy sinh viên.", 404)

    sessions = (
        ExamSession.query.join(Exam, Exam.id == ExamSession.exam_id)
        .filter(Exam.teacher_id == teacher_id, ExamSession.user_id == student.id)
        .order_by(ExamSession.started_at.desc(), ExamSession.id.desc())
        .all()
    )
    attempt_counts = {}
    for session in sessions:
        attempt_counts[session.exam_id] = attempt_counts.get(session.exam_id, 0) + 1

    pending_retakes = {
        permission.exam_id
        for permission in ExamRetakePermission.query.filter_by(
            user_id=student.id, used_at=None
        ).all()
    }

    attempts = []
    seen_by_exam = {}
    for session in sessions:
        seen_by_exam[session.exam_id] = seen_by_exam.get(session.exam_id, 0) + 1
        attempt_number = attempt_counts[session.exam_id] - seen_by_exam[session.exam_id] + 1
        submissions = [
            {
                "title": submission.exercise.title if submission.exercise else "Câu hỏi",
                "status": submission.status,
                "score": submission.score,
                "max_score": submission.max_score,
                "code": submission.code,
                "updated_at": utc_iso(submission.updated_at),
            }
            for submission in [*session.submissions, *session.chapter_submissions]
        ]
        submissions.sort(key=lambda submission: submission["title"].casefold())
        finished_at = session.finished_at
        time_taken_seconds = vietnam_elapsed_seconds(session.started_at, finished_at)

        attempts.append({
            "session_id": session.id,
            "exam_id": session.exam_id,
            "exam_name": session.exam.name,
            "attempt_number": attempt_number,
            "attempt_count": attempt_counts[session.exam_id],
            "max_attempts": session.exam.max_attempts,
            "is_finalized": session.is_finalized,
            "retake_allowed": session.exam_id in pending_retakes,
            "started_at": vietnam_iso(session.started_at),
            "finished_at": vietnam_iso(finished_at),
            "time_taken_seconds": time_taken_seconds,
            "score": session.to_dict()["total_score"],
            "max_score": session.to_dict()["total_max"],
            "correct_count": sum(
                1 for submission in submissions if submission["status"] == "correct"
            ),
            "question_count": len(submissions),
            "submissions": submissions,
        })

    return jsonify({
        "success": True,
        "student": {
            "id": student.id,
            "student_id": student.student_id or "",
            "full_name": student.full_name or "",
            "class_name": student.class_name or "",
            "email": student.email,
        },
        "attempts": attempts,
    }), 200


@teacher_students_bp.route(
    "/<int:student_user_id>/exams/<int:exam_id>/allow-retake", methods=["POST"]
)
@role_required("teacher")
def allow_exam_retake(student_user_id, exam_id):
    teacher_id = int(get_jwt_identity())
    student = User.query.filter_by(id=student_user_id, role="student").first()
    if not student:
        return _json_error("Không tìm thấy sinh viên.", 404)

    exam = Exam.query.filter_by(id=exam_id, teacher_id=teacher_id).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)

    sessions = ExamSession.query.filter_by(
        user_id=student.id, exam_id=exam.id
    ).all()
    if not sessions:
        return _json_error("Sinh viên chưa có lượt làm bài để cấp lại.", 409)

    permission = ExamRetakePermission.query.filter_by(
        user_id=student.id, exam_id=exam.id
    ).first()
    if permission and permission.used_at is None:
        return jsonify({
            "success": True,
            "message": "Sinh viên đã được cấp lượt làm lại.",
            "retake_allowed": True,
        }), 200

    now = vietnam_now_naive()
    permission_time = utc_now_naive()
    for session in sessions:
        if not session.is_finalized:
            session.is_finalized = True
            session.finished_at = now

    if permission:
        permission.granted_by = teacher_id
        permission.granted_at = permission_time
        permission.used_at = None
    else:
        permission = ExamRetakePermission(
            user_id=student.id,
            exam_id=exam.id,
            granted_by=teacher_id,
            granted_at=permission_time,
        )
        db.session.add(permission)

    db.session.commit()
    return jsonify({
        "success": True,
        "message": "Đã cấp lượt làm lại bài thi.",
        "retake_allowed": True,
    }), 200


@teacher_students_bp.route("/<int:student_user_id>", methods=["DELETE"])
@role_required("teacher")
def delete_student(student_user_id):
    student = User.query.filter_by(id=student_user_id, role="student").first()
    if not student:
        return _json_error("Không tìm thấy sinh viên.", 404)

    for session in ChapterSession.query.filter_by(user_id=student.id).all():
        db.session.delete(session)
    for session in ExamSession.query.filter_by(user_id=student.id).all():
        db.session.delete(session)
    for permission in ExamRetakePermission.query.filter_by(user_id=student.id).all():
        db.session.delete(permission)

    LoginLog.query.filter_by(user_id=student.id).delete(synchronize_session=False)
    UserSession.query.filter_by(user_id=student.id).delete(synchronize_session=False)
    db.session.delete(student)
    db.session.commit()
    return jsonify({"success": True, "message": "Đã xóa tài khoản sinh viên và dữ liệu liên quan."}), 200
