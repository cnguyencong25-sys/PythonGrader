from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from extensions import db
from models import (
    Exam, ExamExercise, ExamChapterRule, PublicExamSession, PublicExamSubmission,
    ExamSession, ExamSubmission, ExamChapterSubmission, ExamRetakePermission, Exercise,
    ExamMonitoringRecord, ExamProctoringEvent, User,
)
from decorators import role_required
from exam_proctoring import add_event as add_proctoring_event, get_or_create_record
from datetime import datetime, timedelta
import json
import os
import statistics
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError
from time_utils import (
    VIETNAM_TZ,
    vietnam_elapsed_seconds,
    vietnam_iso,
    vietnam_local_naive,
    vietnam_now_naive,
)
from sample_cases import sample_fields_from_payload

exams_bp = Blueprint("exams", __name__, url_prefix="/api/exams")

def _json_error(msg, code=400):
    return jsonify({"success": False, "message": msg}), code

def _parse_datetime(s):
    if not s: return None
    if not isinstance(s, str):
        return None
    value = s.strip().replace(" ", "T")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=VIETNAM_TZ)
    return parsed.astimezone(VIETNAM_TZ)

# ============================================================
# 1. DANH SÁCH BÀI KIỂM TRA
# ============================================================
@exams_bp.route("", methods=["GET"])
@role_required("teacher")
def list_exams():
    teacher_id = int(get_jwt_identity())
    exams = Exam.query.filter_by(teacher_id=teacher_id).order_by(Exam.created_at.desc()).all()
    return jsonify({"success": True, "exams": [e.to_dict(include_exercises=True, exercises_brief=True) for e in exams]}), 200

# ============================================================
# 2. CHI TIẾT BÀI KIỂM TRA
# ============================================================
@exams_bp.route("/<int:eid>", methods=["GET"])
@role_required("teacher")
def get_exam(eid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam: return _json_error("Không tìm thấy bài kiểm tra.", 404)
    return jsonify({"success": True, "exam": exam.to_dict(include_exercises=True)}), 200

# ============================================================
# 3. TẠO BÀI KIỂM TRA
# ============================================================
@exams_bp.route("", methods=["POST"])
@role_required("teacher")
def create_exam():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    start_time_str = data.get("start_time")
    end_time_str = data.get("end_time")
    duration = data.get("duration_minutes", 45)
    max_attempts = data.get("max_attempts", 1)
    anti_cheat_enabled = data.get("anti_cheat_enabled", True)
    exam_password = (data.get("exam_password") or "").strip()

    if not name or len(name) < 3:
        return _json_error("Tên bài kiểm tra phải có ít nhất 3 ký tự.")
    
    try:
        duration = int(duration)
        if duration <= 0: return _json_error("Thời gian làm bài phải lớn hơn 0.")
    except (ValueError, TypeError):
        return _json_error("Thời gian làm bài không hợp lệ.")
    try:
        max_attempts = int(max_attempts)
        if max_attempts < 1:
            return _json_error("Số lượt làm bài phải ít nhất là 1.")
    except (ValueError, TypeError):
        return _json_error("Số lượt làm bài không hợp lệ.")
    if not isinstance(anti_cheat_enabled, bool):
        return _json_error("Cấu hình chống gian lận không hợp lệ.")

    start_time = _parse_datetime(start_time_str)
    end_time = _parse_datetime(end_time_str)
    
    if (
        start_time
        and end_time
        and vietnam_local_naive(start_time) >= vietnam_local_naive(end_time)
    ):
        return _json_error("Thời gian kết thúc phải sau thời gian bắt đầu.")

    exam = Exam(
        name=name,
        start_time=start_time,
        end_time=end_time,
        duration_minutes=duration,
        max_attempts=max_attempts,
        anti_cheat_enabled=anti_cheat_enabled,
        teacher_id=int(get_jwt_identity())
    )
    exam.set_exam_password(exam_password)
    db.session.add(exam)
    db.session.commit()
    
    return jsonify({"success": True, "message": "Đã tạo bài kiểm tra.", "exam": exam.to_dict(include_exercises=True, exercises_brief=True)}), 201

# ============================================================
# 4. SỬA BÀI KIỂM TRA
# ============================================================
@exams_bp.route("/<int:eid>", methods=["PUT"])
@role_required("teacher")
def update_exam(eid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam: return _json_error("Không tìm thấy bài kiểm tra.", 404)

    data = request.get_json(silent=True) or {}
    
    if "name" in data:
        name = (data.get("name") or "").strip()
        if len(name) < 3: return _json_error("Tên phải có ít nhất 3 ký tự.")
        exam.name = name

    if "start_time" in data:
        exam.start_time = _parse_datetime(data.get("start_time"))
    if "end_time" in data:
        exam.end_time = _parse_datetime(data.get("end_time"))
    
    if (
        exam.start_time
        and exam.end_time
        and vietnam_local_naive(exam.start_time)
        >= vietnam_local_naive(exam.end_time)
    ):
        return _json_error("Thời gian kết thúc phải sau thời gian bắt đầu.")

    if "duration_minutes" in data:
        try:
            duration = int(data.get("duration_minutes"))
            if duration <= 0: return _json_error("Thời gian làm bài phải > 0.")
            exam.duration_minutes = duration
        except (ValueError, TypeError):
            return _json_error("Thời gian làm bài không hợp lệ.")
    if "max_attempts" in data:
        try:
            max_attempts = int(data.get("max_attempts"))
            if max_attempts < 1:
                return _json_error("Số lượt làm bài phải ít nhất là 1.")
            exam.max_attempts = max_attempts
        except (ValueError, TypeError):
            return _json_error("Số lượt làm bài không hợp lệ.")
    if "anti_cheat_enabled" in data:
        anti_cheat_enabled = data.get("anti_cheat_enabled")
        if not isinstance(anti_cheat_enabled, bool):
            return _json_error("Cấu hình chống gian lận không hợp lệ.")
        exam.anti_cheat_enabled = anti_cheat_enabled
    if data.get("clear_exam_password"):
        exam.set_exam_password("")
    elif (data.get("exam_password") or "").strip():
        exam.set_exam_password(data["exam_password"].strip())

    db.session.commit()
    return jsonify({"success": True, "message": "Đã cập nhật bài kiểm tra.", "exam": exam.to_dict(include_exercises=True, exercises_brief=True)}), 200

# ============================================================
# 5. XOÁ BÀI KIỂM TRA
# ============================================================
@exams_bp.route("/<int:eid>", methods=["DELETE"])
@role_required("teacher")
def delete_exam(eid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)

    # 1. Xóa toàn bộ bài nộp và phiên thi của sinh viên đăng nhập thuộc bài kiểm tra này
    session_ids = [s.id for s in ExamSession.query.filter_by(exam_id=exam.id).all()]
    if session_ids:
        ExamSubmission.query.filter(ExamSubmission.session_id.in_(session_ids)).delete(synchronize_session=False)
        ExamChapterSubmission.query.filter(ExamChapterSubmission.session_id.in_(session_ids)).delete(synchronize_session=False)
        ExamSession.query.filter(ExamSession.id.in_(session_ids)).delete(synchronize_session=False)

    # 2. Xóa toàn bộ bài nộp và phiên thi công khai (nếu có)
    public_session_ids = [ps.id for ps in PublicExamSession.query.filter_by(exam_id=exam.id).all()]
    if public_session_ids:
        PublicExamSubmission.query.filter(PublicExamSubmission.session_id.in_(public_session_ids)).delete(synchronize_session=False)
        PublicExamSession.query.filter(PublicExamSession.id.in_(public_session_ids)).delete(synchronize_session=False)

    # 3. Xóa lượt cấp thi lại, quy tắc chọn chương và bài tập riêng của bài kiểm tra này
    ExamRetakePermission.query.filter_by(exam_id=exam.id).delete(synchronize_session=False)
    ExamChapterRule.query.filter_by(exam_id=exam.id).delete(synchronize_session=False)
    ExamExercise.query.filter_by(exam_id=exam.id).delete(synchronize_session=False)

    # 4. Xóa bài kiểm tra chính
    db.session.delete(exam)
    db.session.commit()
    return jsonify({"success": True, "message": "Đã xoá bài kiểm tra."}), 200

# ============================================================
# 6. THÊM BÀI TẬP VÀO BÀI KIỂM TRA
# ============================================================
@exams_bp.route("/<int:eid>/exercises", methods=["POST"])
@role_required("teacher")
def create_exam_exercise(eid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam: return _json_error("Không tìm thấy bài kiểm tra.", 404)

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if len(title) < 3: return _json_error("Tên bài tập phải có ít nhất 3 ký tự.")
    try:
        sample_input, sample_output = sample_fields_from_payload(data)
    except ValueError as error:
        return _json_error(str(error))

    ex = ExamExercise(
        exam_id=exam.id, 
        title=title, 
        description=data.get("description", ""),
        input_format=data.get("input_format", ""),
        output_format=data.get("output_format", ""),
        constraints=data.get("constraints", ""),
        sample_input=sample_input,
        sample_output=sample_output,
        generator_code=data.get("generator_code", ""),
        solution_code=data.get("solution_code", ""),
        num_test_cases=int(data.get("num_test_cases", 10)),
        is_published=True
    )
    db.session.add(ex)
    db.session.commit()
    return jsonify({"success": True, "exercise": ex.to_dict()}), 201

# ============================================================
# 7. CHI TIẾT BÀI TẬP (Giáo viên)
# ============================================================
@exams_bp.route("/exercises/<int:eid>", methods=["GET"])
@role_required("teacher")
def get_exam_exercise(eid):
    ex = ExamExercise.query.get(eid)
    if not ex or ex.exam.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)
    return jsonify({"success": True, "exercise": ex.to_dict()}), 200

# ============================================================
# 8. SỬA BÀI TẬP (Giáo viên)
# ============================================================
@exams_bp.route("/exercises/<int:eid>", methods=["PUT"])
@role_required("teacher")
def update_exam_exercise(eid):
    ex = ExamExercise.query.get(eid)
    if not ex or ex.exam.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)

    data = request.get_json(silent=True) or {}
    if "sample_examples" in data:
        try:
            ex.sample_input, ex.sample_output = sample_fields_from_payload(data)
        except ValueError as error:
            return _json_error(str(error))
    if "title" in data: ex.title = data.get("title", "").strip()
    if "description" in data: ex.description = data.get("description", "").strip()
    if "input_format" in data: ex.input_format = data.get("input_format", "")
    if "output_format" in data: ex.output_format = data.get("output_format", "")
    if "constraints" in data: ex.constraints = data.get("constraints", "")
    if "sample_examples" not in data:
        if "sample_input" in data: ex.sample_input = data.get("sample_input", "")
        if "sample_output" in data: ex.sample_output = data.get("sample_output", "")
    if "generator_code" in data: ex.generator_code = data.get("generator_code", "")
    if "solution_code" in data: ex.solution_code = data.get("solution_code", "")
    if "num_test_cases" in data: ex.num_test_cases = int(data.get("num_test_cases", 10))

    db.session.commit()
    return jsonify({"success": True, "exercise": ex.to_dict()}), 200

# ============================================================
# 9. XOÁ BÀI TẬP (Giáo viên)
# ============================================================
@exams_bp.route("/exercises/<int:eid>", methods=["DELETE"])
@role_required("teacher")
def delete_exam_exercise(eid):
    ex = ExamExercise.query.get(eid)
    if not ex or ex.exam.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)
    db.session.delete(ex)
    db.session.commit()
    return jsonify({"success": True}), 200

# ============================================================
# 10. API ẨN/XUẤT BẢN BÀI TẬP
# ============================================================
@exams_bp.route("/exercises/<int:eid>/toggle-publish", methods=["POST"])
@role_required("teacher")
def toggle_exam_exercise(eid):
    ex = ExamExercise.query.get(eid)
    if not ex or ex.exam.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)
    ex.is_published = not ex.is_published
    db.session.commit()
    return jsonify({"success": True, "is_published": ex.is_published}), 200


@exams_bp.route("/<int:eid>/chapter-rules", methods=["GET", "PUT"])
@role_required("teacher")
def exam_chapter_rules(eid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)

    if request.method == "GET":
        return jsonify({"success": True, "rules": [
            {"chapter_id": rule.chapter_id, "chapter_name": rule.chapter.name, "question_count": rule.question_count}
            for rule in exam.chapter_rules
        ]}), 200

    data = request.get_json(silent=True) or {}
    rules = data.get("rules")
    if not isinstance(rules, list):
        return _json_error("Danh sách chương không hợp lệ.")
    normalized = []
    seen = set()
    from models import Chapter
    for item in rules:
        try:
            chapter_id = int(item.get("chapter_id"))
            count = int(item.get("question_count"))
        except (AttributeError, TypeError, ValueError):
            return _json_error("Chương hoặc số câu hỏi không hợp lệ.")
        chapter = Chapter.query.filter_by(id=chapter_id, teacher_id=teacher_id).first()
        if not chapter or chapter_id in seen or count < 1:
            return _json_error("Chương không hợp lệ hoặc số câu hỏi phải lớn hơn 0.")
        available = Exercise.query.filter_by(chapter_id=chapter_id, is_published=True).count()
        if count > available:
            return _json_error(f"Chương {chapter.name} chỉ có {available} câu hỏi đã xuất bản.")
        normalized.append((chapter_id, count))
        seen.add(chapter_id)

    ExamChapterRule.query.filter_by(exam_id=eid).delete()
    for chapter_id, count in normalized:
        db.session.add(ExamChapterRule(exam_id=eid, chapter_id=chapter_id, question_count=count))
    db.session.commit()
    return jsonify({"success": True, "rules": [
        {"chapter_id": rule.chapter_id, "chapter_name": rule.chapter.name, "question_count": rule.question_count}
        for rule in exam.chapter_rules
    ]}), 200


def _matches_score_filters(started_at, class_name, student_id, full_name):
    exam_day = request.args.get("date", "").strip()
    filters = (
        (request.args.get("class_name", "").strip(), class_name),
        (request.args.get("student_id", "").strip(), student_id),
        (request.args.get("full_name", "").strip(), full_name),
    )
    if exam_day and started_at.date().isoformat() != exam_day:
        return False
    return all(not expected or expected.casefold() in actual.casefold() for expected, actual in filters)


def _format_time_taken(started_at, finished_at):
    seconds = vietnam_elapsed_seconds(started_at, finished_at)
    return str(timedelta(seconds=seconds)) if seconds is not None else ""


def _submission_review_item(submission, question_key, title):
    if submission.status == "pending" or not submission.code.strip():
        return None
    return {
        "question_key": question_key,
        "title": title,
        "code": submission.code,
        "status": submission.status,
        "score": submission.score,
        "max_score": submission.max_score,
    }


def _authenticated_review_submissions(session):
    submissions_by_key = {}
    for submission in session.submissions:
        question_key = f"exam-{submission.exercise_id}"
        submissions_by_key[question_key] = _submission_review_item(
            submission,
            question_key,
            submission.exercise.title if submission.exercise else question_key,
        )
    for submission in session.chapter_submissions:
        question_key = f"chapter-{submission.exercise_id}"
        submissions_by_key[question_key] = _submission_review_item(
            submission,
            question_key,
            submission.exercise.title if submission.exercise else question_key,
        )

    try:
        question_keys = json.loads(session.question_ids or "[]")
    except (TypeError, ValueError):
        question_keys = []
    if not isinstance(question_keys, list):
        question_keys = []
    ordered_keys = [
        key for key in question_keys
        if isinstance(key, str) and key in submissions_by_key
    ]
    ordered_keys.extend(key for key in submissions_by_key if key not in ordered_keys)
    return [
        submissions_by_key[key]
        for key in ordered_keys
        if submissions_by_key[key] is not None
    ]


def _public_review_submissions(session):
    submissions_by_key = {
        submission.question_key: submission
        for submission in session.submissions
    }
    try:
        question_keys = json.loads(session.question_ids or "[]")
    except (TypeError, ValueError):
        question_keys = []
    if not isinstance(question_keys, list):
        question_keys = []
    ordered_keys = [
        key for key in question_keys
        if isinstance(key, str) and key in submissions_by_key
    ]
    ordered_keys.extend(key for key in submissions_by_key if key not in ordered_keys)

    review_submissions = []
    for question_key in ordered_keys:
        submission = submissions_by_key[question_key]
        kind, _, raw_id = question_key.partition("-")
        try:
            question_id = int(raw_id)
        except ValueError:
            question_id = None
        question = None
        if question_id is not None and kind == "exam":
            question = ExamExercise.query.filter_by(
                id=question_id, exam_id=session.exam_id
            ).first()
        elif question_id is not None and kind == "chapter":
            question = Exercise.query.get(question_id)
        item = _submission_review_item(
            submission,
            question_key,
            question.title if question else question_key,
        )
        if item is not None:
            review_submissions.append(item)
    return review_submissions


def _filtered_score_rows(exam_id):
    rows = []
    exam = db.session.get(Exam, exam_id)
    anti_cheat_enabled = bool(exam and exam.anti_cheat_enabled)
    records = (
        ExamMonitoringRecord.query.filter_by(exam_id=exam_id).all()
        if anti_cheat_enabled else []
    )
    records_by_user = {record.user_id: record for record in records}
    for session in PublicExamSession.query.filter_by(exam_id=exam_id, is_finalized=True).all():
        if not _matches_score_filters(
            session.started_at, session.class_name, session.student_id, session.full_name
        ):
            continue
        totals = session.to_dict()
        review_submissions = _public_review_submissions(session)
        rows.append({
            "session_id": session.id, "student_id": session.student_id,
            "full_name": session.full_name, "class_name": session.class_name,
            "score": totals["total_score"], "max_score": totals["total_max"],
            "time_taken": _format_time_taken(session.started_at, session.finished_at),
            "exam_date": session.started_at.date().isoformat(),
            "violation_count": session.violation_count if anti_cheat_enabled else 0,
            "started_at": vietnam_iso(session.started_at),
            "finished_at": vietnam_iso(session.finished_at),
            "email": "",
            "status": (
                "Chưa nộp" if not review_submissions
                else "Nghi vấn gian lận"
                if anti_cheat_enabled and session.violation_count else "Hoàn thành"
            ),
            "submissions": review_submissions,
        })
    for session in ExamSession.query.filter_by(exam_id=exam_id, is_finalized=True).all():
        if not session.user:
            continue
        class_name = session.user.class_name or ""
        student_id = session.user.student_id or ""
        full_name = session.user.full_name or ""
        if not _matches_score_filters(session.started_at, class_name, student_id, full_name):
            continue
        totals = session.to_dict()
        review_submissions = _authenticated_review_submissions(session)
        record = records_by_user.get(session.user_id) if anti_cheat_enabled else None
        is_blocked = bool(
            record and record.is_blocked and record.current_session_id == session.id
        )
        rows.append({
            "session_id": session.id, "student_id": student_id, "full_name": full_name,
            "class_name": class_name,
            "score": 0.0 if is_blocked else totals["total_score"],
            "max_score": totals["total_max"],
            "time_taken": _format_time_taken(session.started_at, session.finished_at),
            "exam_date": session.started_at.date().isoformat(),
            "violation_count": record.abnormal_count if record else 0,
            "started_at": vietnam_iso(session.started_at),
            "finished_at": vietnam_iso(session.finished_at),
            "email": session.user.email,
            "status": "Gian lận" if is_blocked or (record and record.is_cheating) else (
                "Chưa nộp" if not review_submissions
                else "Hoàn thành"
            ),
            "submissions": review_submissions,
        })

    existing_session_ids = {row["session_id"] for row in rows}
    for record in records:
        session = record.current_session
        if (
            not record.is_blocked
            or not session
            or session.is_finalized
            or session.id in existing_session_ids
            or not session.user
        ):
            continue
        student = session.user
        class_name = student.class_name or ""
        student_id = student.student_id or ""
        full_name = student.full_name or ""
        if not _matches_score_filters(session.started_at, class_name, student_id, full_name):
            continue
        rows.append({
            "session_id": session.id,
            "student_id": student_id,
            "full_name": full_name,
            "class_name": class_name,
            "score": 0.0,
            "max_score": 10.0,
            "time_taken": _format_time_taken(session.started_at, record.blocked_at),
            "exam_date": session.started_at.date().isoformat(),
            "violation_count": record.abnormal_count,
            "started_at": vietnam_iso(session.started_at),
            "finished_at": vietnam_iso(record.blocked_at),
            "email": student.email,
            "status": "Gian lận",
            "submissions": _authenticated_review_submissions(session),
        })
    rows.sort(key=lambda row: row["started_at"], reverse=True)
    return rows


@exams_bp.route("/<int:eid>/scores", methods=["GET"])
@role_required("teacher")
def exam_scores(eid):
    exam = Exam.query.filter_by(id=eid, teacher_id=int(get_jwt_identity())).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)
    return jsonify({"success": True, "scores": _filtered_score_rows(eid)}), 200


@exams_bp.route("/<int:eid>/monitor", methods=["GET"])
@role_required("teacher")
def exam_monitor(eid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)
    if not exam.anti_cheat_enabled:
        return _json_error("Chế độ chống gian lận chưa được bật cho bài kiểm tra này.", 403)

    users = User.query.filter_by(role="student").order_by(
        User.student_id.asc(), User.full_name.asc(), User.id.asc()
    ).all()
    records = ExamMonitoringRecord.query.filter_by(exam_id=eid).all()
    records_by_user = {record.user_id: record for record in records}
    sessions = ExamSession.query.filter_by(exam_id=eid).order_by(
        ExamSession.started_at.desc(), ExamSession.id.desc()
    ).all()
    sessions_by_user = {}
    for session in sessions:
        sessions_by_user.setdefault(session.user_id, session)
    events_by_record = {}
    if records:
        events = ExamProctoringEvent.query.filter(
            ExamProctoringEvent.record_id.in_([record.id for record in records])
        ).order_by(ExamProctoringEvent.occurred_at.desc()).all()
        for event in events:
            grouped = events_by_record.setdefault(event.record_id, [])
            if len(grouped) < 20:
                grouped.append({
                    "event_type": event.event_type,
                    "detail": event.detail,
                    "occurred_at": vietnam_iso(event.occurred_at),
                })

    participants = []
    for user in users:
        record = records_by_user.get(user.id)
        session = None
        if record and record.current_session_id:
            session = db.session.get(ExamSession, record.current_session_id)
        if not session:
            session = sessions_by_user.get(user.id)

        if record and (record.is_blocked or record.is_cheating):
            status = "cheating"
        elif session and not session.is_finalized:
            status = "in_progress"
        elif session:
            status = "completed"
        else:
            status = "not_started"

        participants.append({
            "user_id": user.id,
            "student_id": user.student_id or "",
            "full_name": user.full_name or user.email,
            "status": status,
            "abnormal_count": record.abnormal_count if record else 0,
            "is_blocked": bool(record and record.is_blocked),
            "session_id": session.id if session else None,
            "events": events_by_record.get(record.id, []) if record else [],
        })

    return jsonify({
        "success": True,
        "exam": {"id": exam.id, "name": exam.name},
        "participants": participants,
        "updated_at": vietnam_iso(vietnam_now_naive()),
    }), 200


@exams_bp.route(
    "/<int:eid>/monitor/students/<int:uid>/toggle-block",
    methods=["POST"],
)
@role_required("teacher")
def toggle_exam_participant_block(eid, uid):
    teacher_id = int(get_jwt_identity())
    exam = Exam.query.filter_by(id=eid, teacher_id=teacher_id).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)
    if not exam.anti_cheat_enabled:
        return _json_error("Chế độ chống gian lận chưa được bật cho bài kiểm tra này.", 403)
    student = User.query.filter_by(id=uid, role="student").first()
    if not student:
        return _json_error("Không tìm thấy sinh viên.", 404)

    current_session = ExamSession.query.filter_by(
        exam_id=eid,
        user_id=uid,
    ).order_by(ExamSession.started_at.desc(), ExamSession.id.desc()).first()
    record = get_or_create_record(
        exam_id=eid,
        user_id=uid,
        session_id=current_session.id if current_session else None,
    )

    if record.is_blocked:
        record.is_blocked = False
        record.is_cheating = False
        record.blocked_at = None
        action = "teacher_unblock"
        detail = "Giáo viên đã bỏ chặn bài kiểm tra"
    else:
        record.is_blocked = True
        record.is_cheating = True
        record.blocked_at = vietnam_now_naive()
        action = "teacher_block"
        detail = "Giáo viên đã chặn bài kiểm tra; điểm được chốt 0"
    add_proctoring_event(
        record,
        action,
        detail,
        session_id=record.current_session_id,
    )
    db.session.commit()
    return jsonify({
        "success": True,
        "is_blocked": record.is_blocked,
        "is_cheating": record.is_cheating,
        "abnormal_count": record.abnormal_count,
    }), 200


@exams_bp.route("/<int:eid>/export-sheet", methods=["POST"])
@role_required("teacher")
def export_scores_to_sheet(eid):
    exam = Exam.query.filter_by(id=eid, teacher_id=int(get_jwt_identity())).first()
    if not exam:
        return _json_error("Không tìm thấy bài kiểm tra.", 404)
    webhook_url = os.getenv("GOOGLE_SHEETS_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return _json_error("Chưa cấu hình GOOGLE_SHEETS_WEBHOOK_URL cho Google Sheets.", 503)

    scores = _filtered_score_rows(eid)
    scores.sort(key=lambda row: (
        -float(row["score"]),
        row["finished_at"] or "9999-12-31T23:59:59+07:00",
        int(row["violation_count"]),
        row["student_id"].casefold(),
        row["full_name"].casefold(),
    ))
    for rank, score in enumerate(scores, start=1):
        score["rank"] = rank

    numeric_scores = [float(score["score"]) for score in scores]
    payload = {
        "version": 2,
        "exam": exam.name,
        "report": {
            "exam_name": exam.name,
            "duration_minutes": exam.duration_minutes,
            "exported_at": vietnam_iso(vietnam_now_naive()),
            "participant_count": len(scores),
            "average_score": round(statistics.mean(numeric_scores), 2) if numeric_scores else None,
            "highest_score": max(numeric_scores) if numeric_scores else None,
            "lowest_score": min(numeric_scores) if numeric_scores else None,
        },
        "scores": [{
            "rank": score["rank"],
            "student_id": score["student_id"],
            "full_name": score["full_name"],
            "class_name": score["class_name"],
            "email": score["email"],
            "score": score["score"],
            "max_score": score["max_score"],
            "finished_at": score["finished_at"],
            "violation_count": score["violation_count"],
            "status": score["status"],
        } for score in scores],
    }
    request_to_sheet = Request(
        webhook_url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urlopen(request_to_sheet, timeout=15) as response:
            if response.status < 200 or response.status >= 300:
                return _json_error("Google Sheets không nhận được dữ liệu.", 502)
            response_body = response.read()
    except (HTTPError, URLError, TimeoutError, OSError):
        return _json_error("Không thể kết nối dịch vụ Google Sheets. Vui lòng thử lại.", 502)

    try:
        result = json.loads(response_body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return _json_error("Webhook cần trả về JSON có liên kết Google Sheets.", 502)
    if not isinstance(result, dict):
        return _json_error("Webhook trả về dữ liệu không hợp lệ.", 502)
    spreadsheet_url = result.get("spreadsheetUrl") or result.get("url")
    if not result.get("success") or not isinstance(spreadsheet_url, str):
        return _json_error(
            result.get("message") or "Webhook chưa trả về liên kết Google Sheets.",
            502,
        )
    if not spreadsheet_url.startswith("https://docs.google.com/spreadsheets/"):
        return _json_error("Webhook trả về liên kết Google Sheets không hợp lệ.", 502)
    return jsonify({
        "success": True,
        "message": "Đã tạo báo cáo xếp hạng trên Google Sheets.",
        "url": spreadsheet_url,
    }), 200