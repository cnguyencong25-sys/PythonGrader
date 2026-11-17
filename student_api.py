from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from extensions import db
from models import (
    Chapter, Exercise, ChapterSession, ChapterSubmission, 
    Exam, ExamExercise, ExamSession, ExamSubmission, ExamChapterSubmission,
    ExamRetakePermission,
    ExamChapterRule, PublicExamSession, PublicExamSubmission
)
from decorators import role_required
from judge import evaluate_submission # ⭐ Import module chấm điểm tự động
from time_utils import vietnam_iso, vietnam_now_naive
import random
import json
import hashlib
import secrets
from datetime import timedelta
from time_utils import utc_now_naive

student_api_bp = Blueprint("student_api", __name__, url_prefix="/api/student")
public_exam_bp = Blueprint("public_exam", __name__, url_prefix="/api/public-exams")

def _json_error(msg, code=400):
    return jsonify({"success": False, "message": msg}), code


# ============================================================
# PHẦN 1: LUYỆN TẬP CHƯƠNG
# ============================================================

@student_api_bp.route("/chapters", methods=["GET"])
@role_required("student")
def get_chapters():
    user_id = int(get_jwt_identity())
    chapters = Chapter.query.order_by(Chapter.created_at.desc()).all()
    
    sessions = ChapterSession.query.filter_by(user_id=user_id, is_finalized=True).all()
    
    chapter_scores = {}
    for s in sessions:
        if s.chapter_id not in chapter_scores:
            chapter_scores[s.chapter_id] = 0
        chapter_scores[s.chapter_id] = max(chapter_scores[s.chapter_id], s.to_dict()["total_score"])

    result = []
    for c in chapters:
        result.append({
            "id": c.id,
            "name": c.name,
            "mode": c.mode,
            "total_exercises": len([ex for ex in c.exercises if ex.is_published]), # Chỉ đếm bài đã xuất bản
            "teacher_name": c.teacher.full_name or c.teacher.email,
            "best_score": chapter_scores.get(c.id, None)
        })

    return jsonify({"success": True, "chapters": result}), 200


@student_api_bp.route("/chapters/<int:cid>", methods=["GET"])
@role_required("student")
def get_chapter_detail(cid):
    user_id = int(get_jwt_identity())
    chapter = Chapter.query.get(cid)
    if not chapter:
        return _json_error("Không tìm thấy chương.", 404)

    active_session = ChapterSession.query.filter_by(
        user_id=user_id, chapter_id=cid, is_finalized=False
    ).order_by(ChapterSession.started_at.desc()).first()

    history_sessions = ChapterSession.query.filter_by(
        user_id=user_id, chapter_id=cid, is_finalized=True
    ).order_by(ChapterSession.finished_at.desc()).all()

    # ⭐ Chỉ lấy các bài được xuất bản
    exercises = [ex for ex in chapter.exercises if ex.is_published]
    
    ex_list = [ex.to_dict() for ex in exercises]

    return jsonify({
        "success": True,
        "chapter": {
            "id": chapter.id,
            "name": chapter.name,
            "mode": "practice",
            "exercises": ex_list
        },
        "active_session_id": active_session.id if active_session else None,
        "history": [h.to_dict() for h in history_sessions]
    }), 200


@student_api_bp.route("/chapters/<int:cid>/start", methods=["POST"])
@role_required("student")
def start_chapter(cid):
    user_id = int(get_jwt_identity())
    chapter = Chapter.query.get(cid)
    if not chapter: return _json_error("Không tìm thấy chương.", 404)

    old_sessions = ChapterSession.query.filter_by(user_id=user_id, chapter_id=cid, is_finalized=False).all()
    for s in old_sessions: db.session.delete(s)
    
    new_session = ChapterSession(user_id=user_id, chapter_id=cid)
    db.session.add(new_session)
    db.session.commit()

    return jsonify({"success": True, "session_id": new_session.id}), 201


@student_api_bp.route("/sessions/<int:sid>", methods=["GET"])
@role_required("student")
def get_session_data(sid):
    user_id = int(get_jwt_identity())
    session = ChapterSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Không tìm thấy phiên làm bài.", 404)

    chapter = session.chapter
    exercises = [ex for ex in chapter.exercises if ex.is_published]
    
    ex_list = [ex.to_dict() for ex in exercises]
    subs = {s.exercise_id: s.to_dict() for s in session.submissions}

    return jsonify({
        "success": True,
        "chapter": {
            "id": chapter.id,
            "name": chapter.name,
            "mode": "practice",
            "exercises": ex_list
        },
        "submissions": subs
    }), 200


@student_api_bp.route("/sessions/<int:sid>/save-draft", methods=["POST"])
@role_required("student")
def save_draft(sid):
    user_id = int(get_jwt_identity())
    session = ChapterSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Không tìm thấy phiên.", 404)

    data = request.get_json(silent=True) or {}
    ex_id = data.get("exercise_id")
    code = data.get("code", "")

    sub = ChapterSubmission.query.filter_by(session_id=sid, exercise_id=ex_id).first()
    if not sub:
        sub = ChapterSubmission(session_id=sid, exercise_id=ex_id)
        db.session.add(sub)
    
    sub.code = code
    db.session.commit()
    return jsonify({"success": True}), 200


@student_api_bp.route("/sessions/<int:sid>/submit", methods=["POST"])
@role_required("student")
def submit_code(sid):
    user_id = int(get_jwt_identity())
    session = ChapterSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Không tìm thấy phiên.", 404)

    data = request.get_json(silent=True) or {}
    exercise_id = data.get("exercise_id")
    code = data.get("code", "")

    exercise = Exercise.query.get(exercise_id)
    if not exercise: return _json_error("Không tìm thấy bài tập.", 404)

    # ⭐ GỌI MODULE CHẤM ĐIỂM TỰ ĐỘNG
    result = evaluate_submission(
        student_code=code,
        generator_code=exercise.generator_code,
        solution_code=exercise.solution_code,
        num_tests=exercise.num_test_cases
    )

    sub = ChapterSubmission.query.filter_by(session_id=sid, exercise_id=exercise_id).first()
    if not sub:
        sub = ChapterSubmission(session_id=sid, exercise_id=exercise_id)
        db.session.add(sub)

    sub.code = code
    sub.status = result["status"]
    sub.score = result["score"]
    sub.max_score = result["max_score"]
    db.session.commit()

    return jsonify({"success": True, "result": sub.to_dict()}), 200


@student_api_bp.route("/sessions/<int:sid>/finish", methods=["POST"])
@role_required("student")
def finish_session(sid):
    user_id = int(get_jwt_identity())
    session = ChapterSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Không tìm thấy phiên.", 404)

    session.is_finalized = True
    session.finished_at = utc_now_naive()
    db.session.commit()

    return jsonify({"success": True}), 200


# ============================================================
# PHẦN 2: BÀI KIỂM TRA
# ============================================================

def _select_exam_question_keys(exam):
    rules = ExamChapterRule.query.filter_by(exam_id=exam.id).all()
    if rules:
        question_keys = []
        for rule in rules:
            available = Exercise.query.filter_by(
                chapter_id=rule.chapter_id, is_published=True
            ).all()
            if rule.question_count > len(available):
                return None, "Ngân hàng câu hỏi đã thay đổi; giáo viên cần cập nhật số câu theo chương.", 409
            question_keys.extend(
                f"chapter-{exercise.id}"
                for exercise in random.sample(available, rule.question_count)
            )
    else:
        question_keys = [
            f"exam-{exercise.id}"
            for exercise in exam.exercises
            if exercise.is_published
        ]
    if not question_keys:
        return None, "Bài thi chưa có câu hỏi được xuất bản.", 400
    return question_keys, None, None


def _exam_session_question_keys(session):
    try:
        question_keys = json.loads(session.question_ids or "[]")
    except (TypeError, ValueError):
        question_keys = []
    if (
        isinstance(question_keys, list)
        and question_keys
        and all(
            isinstance(key, str)
            and key.startswith(("exam-", "chapter-"))
            and key.split("-", 1)[1].isdecimal()
            for key in question_keys
        )
    ):
        return question_keys, None, None
    question_keys, message, status = _select_exam_question_keys(session.exam)
    if message:
        return None, message, status
    session.question_ids = json.dumps(question_keys)
    return question_keys, None, None


def _resolve_exam_question(question_key, exam):
    if not isinstance(question_key, str) or "-" not in question_key:
        return None, None
    kind, raw_id = question_key.split("-", 1)
    try:
        exercise_id = int(raw_id)
    except ValueError:
        return None, None
    if kind == "exam":
        exercise = ExamExercise.query.filter_by(
            id=exercise_id, exam_id=exam.id, is_published=True
        ).first()
        return exercise, False
    if kind == "chapter":
        exercise = (
            Exercise.query.join(Chapter, Exercise.chapter_id == Chapter.id)
            .filter(
                Exercise.id == exercise_id,
                Exercise.is_published.is_(True),
                Chapter.teacher_id == exam.teacher_id,
            )
            .first()
        )
        return exercise, True
    return None, None


def _exam_question_key_from_request(submitted_id, question_keys):
    if isinstance(submitted_id, bool):
        return None
    if isinstance(submitted_id, int):
        question_key = f"exam-{submitted_id}"
    elif isinstance(submitted_id, str):
        question_key = submitted_id
        if question_key.isdecimal():
            question_key = f"exam-{question_key}"
    else:
        return None
    return question_key if question_key in question_keys else None


def _student_exam_question_data(question_key, exam):
    exercise, _ = _resolve_exam_question(question_key, exam)
    if not exercise:
        return None
    examples = exercise.sample_examples
    return {
        "id": question_key,
        "title": exercise.title,
        "description": exercise.description,
        "input_format": exercise.input_format,
        "output_format": exercise.output_format,
        "constraints": exercise.constraints,
        "sample_input": examples[0]["input"] if examples else "",
        "sample_output": examples[0]["output"] if examples else "",
        "sample_examples": examples,
    }


@student_api_bp.route("/exams", methods=["GET"])
@role_required("student")
def get_exams():
    user_id = int(get_jwt_identity())
    exams = Exam.query.order_by(Exam.created_at.desc()).all()
    
    sessions = ExamSession.query.filter_by(user_id=user_id).all()
    finalized_counts = {}
    active_exam_ids = set()
    scores = {}
    for s in sessions:
        if not s.is_finalized:
            active_exam_ids.add(s.exam_id)
            continue
        finalized_counts[s.exam_id] = finalized_counts.get(s.exam_id, 0) + 1
        current_score = s.to_dict()["total_score"]
        scores[s.exam_id] = max(scores.get(s.exam_id, 0), current_score)

    pending_retakes = {
        permission.exam_id
        for permission in ExamRetakePermission.query.filter_by(user_id=user_id, used_at=None).all()
    }

    result = []
    for e in exams:
        attempts_used = finalized_counts.get(e.id, 0)
        configured_question_count = sum(rule.question_count for rule in e.chapter_rules)
        can_start = (
            e.id in active_exam_ids
            or attempts_used < e.max_attempts
            or e.id in pending_retakes
        )
        result.append({
            "id": e.id,
            "name": e.name,
            "duration_minutes": e.duration_minutes,
            "max_attempts": e.max_attempts,
            "start_time": vietnam_iso(e.start_time),
            "end_time": vietnam_iso(e.end_time),
            "exercise_count": configured_question_count or len(
                [ex for ex in e.exercises if ex.is_published]
            ),
            "best_score": scores.get(e.id, None),
            "attempts_used": attempts_used,
            "has_active_session": e.id in active_exam_ids,
            "can_start": can_start,
            "is_completed": attempts_used > 0 and not can_start,
            "retake_allowed": e.id in pending_retakes,
            "password_configured": bool(e.password_hash),
        })
    return jsonify({"success": True, "exams": result}), 200


@student_api_bp.route("/exams/<int:eid>/start", methods=["POST"])
@role_required("student")
def start_exam(eid):
    user_id = int(get_jwt_identity())
    exam = Exam.query.get(eid)
    if not exam: return _json_error("Không tìm thấy bài kiểm tra.", 404)

    now = vietnam_now_naive()
    if exam.start_time and now < exam.start_time:
        return _json_error("Chưa đến giờ làm bài.", 403)
    if exam.end_time and now > exam.end_time:
        return _json_error("Đã hết thời gian làm bài.", 403)

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _json_error("Dữ liệu yêu cầu không hợp lệ.")
    password = data.get("password", "")
    if not isinstance(password, str):
        return _json_error("Mật khẩu bài thi không hợp lệ.")
    if exam.password_hash and not exam.check_exam_password(password):
        return _json_error("Mật khẩu bài thi không chính xác.", 403)

    old = ExamSession.query.filter_by(user_id=user_id, exam_id=eid, is_finalized=False).first()
    if old:
        allowed_end_t = old.started_at + timedelta(minutes=exam.duration_minutes)
        if exam.end_time:
            allowed_end_t = min(allowed_end_t, exam.end_time)
            
        if now < allowed_end_t:
            question_keys, message, status = _exam_session_question_keys(old)
            if message:
                return _json_error(message, status)
            old.question_ids = json.dumps(question_keys)
            db.session.commit()
            return jsonify({"success": True, "session_id": old.id, "is_resumed": True}), 200
        else:
            old.is_finalized = True
            old.finished_at = now
            db.session.commit()

    finalized_count = ExamSession.query.filter_by(
        user_id=user_id, exam_id=eid, is_finalized=True
    ).count()
    retake_permission = ExamRetakePermission.query.filter_by(
        user_id=user_id, exam_id=eid, used_at=None
    ).first()
    if finalized_count >= exam.max_attempts and not retake_permission:
        return _json_error("Bạn đã hết lượt làm bài kiểm tra này.", 403)

    question_keys, message, status = _select_exam_question_keys(exam)
    if message:
        return _json_error(message, status)
    new_sess = ExamSession(
        user_id=user_id,
        exam_id=eid,
        started_at=now,
        question_ids=json.dumps(question_keys),
    )
    db.session.add(new_sess)
    if retake_permission:
        retake_permission.used_at = utc_now_naive()
    db.session.commit()
    return jsonify({"success": True, "session_id": new_sess.id, "is_resumed": False}), 201


@student_api_bp.route("/exam-sessions/<int:sid>", methods=["GET"])
@role_required("student")
def get_exam_session(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Không tìm thấy phiên làm bài.", 404)

    exam = session.exam
    now = vietnam_now_naive()

    if exam.end_time and now > exam.end_time:
        return _json_error("Đã hết thời gian làm bài.", 403)
        
    allowed_end_t = session.started_at + timedelta(minutes=exam.duration_minutes)
    if exam.end_time:
        allowed_end_t = min(allowed_end_t, exam.end_time)

    remain_seconds = int((allowed_end_t - now).total_seconds())
    if remain_seconds <= 0:
        return _json_error("Đã hết thời gian làm bài.", 403)

    question_keys, message, status = _exam_session_question_keys(session)
    if message:
        return _json_error(message, status)
    db.session.commit()
    ex_list = [
        question
        for question in (
            _student_exam_question_data(key, session.exam) for key in question_keys
        )
        if question
    ]
    subs = {}
    for key in question_keys:
        exercise, is_chapter_question = _resolve_exam_question(key, session.exam)
        if not exercise:
            continue
        if is_chapter_question:
            submission = ExamChapterSubmission.query.filter_by(
                session_id=session.id, exercise_id=exercise.id
            ).first()
        else:
            submission = ExamSubmission.query.filter_by(
                session_id=session.id, exercise_id=exercise.id
            ).first()
        if submission:
            subs[key] = submission.to_dict()

    return jsonify({
        "success": True,
        "exam": {
            "id": exam.id,
            "name": exam.name,
            "exercises": ex_list
        },
        "submissions": subs,
        "remain_seconds": remain_seconds
    }), 200


@student_api_bp.route("/exam-sessions/<int:sid>/save-draft", methods=["POST"])
@role_required("student")
def save_exam_draft(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Lỗi phiên làm bài.", 404)
    
    if session.exam.end_time and vietnam_now_naive() > session.exam.end_time:
        return _json_error("Đã hết giờ.", 403)

    data = request.get_json(silent=True) or {}
    question_keys, message, status = _exam_session_question_keys(session)
    if message:
        return _json_error(message, status)
    question_key = _exam_question_key_from_request(data.get("exercise_id"), question_keys)
    code = data.get("code", "")
    if not question_key or not isinstance(code, str):
        return _json_error("Câu hỏi hoặc mã nguồn không hợp lệ.")
    exercise, is_chapter_question = _resolve_exam_question(question_key, session.exam)
    if not exercise:
        return _json_error("Không tìm thấy câu hỏi.", 404)

    if is_chapter_question:
        sub = ExamChapterSubmission.query.filter_by(
            session_id=sid, exercise_id=exercise.id
        ).first()
    else:
        sub = ExamSubmission.query.filter_by(
            session_id=sid, exercise_id=exercise.id
        ).first()
    if not sub:
        submission_model = ExamChapterSubmission if is_chapter_question else ExamSubmission
        sub = submission_model(session_id=sid, exercise_id=exercise.id)
        db.session.add(sub)
    sub.code = code
    db.session.commit()
    return jsonify({"success": True}), 200


@student_api_bp.route("/exam-sessions/<int:sid>/submit", methods=["POST"])
@role_required("student")
def submit_exam_code(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Lỗi phiên làm bài.", 404)

    if session.exam.end_time and vietnam_now_naive() > session.exam.end_time:
        return _json_error("Đã hết giờ, không thể nộp.", 403)

    data = request.get_json(silent=True) or {}
    question_keys, message, status = _exam_session_question_keys(session)
    if message:
        return _json_error(message, status)
    question_key = _exam_question_key_from_request(data.get("exercise_id"), question_keys)
    code = data.get("code", "")
    if not question_key or not isinstance(code, str):
        return _json_error("Câu hỏi hoặc mã nguồn không hợp lệ.")
    exercise, is_chapter_question = _resolve_exam_question(question_key, session.exam)
    if not exercise:
        return _json_error("Không tìm thấy bài tập.", 404)

    # ⭐ GỌI MODULE CHẤM ĐIỂM TỰ ĐỘNG
    result = evaluate_submission(
        student_code=code,
        generator_code=exercise.generator_code,
        solution_code=exercise.solution_code,
        num_tests=exercise.num_test_cases
    )

    if is_chapter_question:
        sub = ExamChapterSubmission.query.filter_by(
            session_id=sid, exercise_id=exercise.id
        ).first()
    else:
        sub = ExamSubmission.query.filter_by(
            session_id=sid, exercise_id=exercise.id
        ).first()
    if not sub:
        submission_model = ExamChapterSubmission if is_chapter_question else ExamSubmission
        sub = submission_model(session_id=sid, exercise_id=exercise.id)
        db.session.add(sub)
    sub.code = code
    sub.status = result["status"]
    sub.score = result["score"]
    sub.max_score = result["max_score"]
    db.session.commit()

    return jsonify({"success": True, "result": sub.to_dict()}), 200


@student_api_bp.route("/exam-sessions/<int:sid>/finish", methods=["POST"])
@role_required("student")
def finish_exam(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Lỗi phiên làm bài.", 404)

    session.is_finalized = True
    session.finished_at = vietnam_now_naive()
    db.session.commit()
    return jsonify({"success": True}), 200


@student_api_bp.route("/exams/<int:eid>/history", methods=["GET"])
@role_required("student")
def get_exam_history(eid):
    user_id = int(get_jwt_identity())
    exam = Exam.query.get(eid)
    if not exam: return _json_error("Không tìm thấy bài kiểm tra.", 404)

    session = ExamSession.query.filter_by(
        user_id=user_id, exam_id=eid, is_finalized=True
    ).order_by(ExamSession.finished_at.desc()).first()

    if not session:
        return _json_error("Bạn chưa làm bài kiểm tra này.", 404)

    return jsonify({
        "success": True,
        "history": session.to_dict()
    }), 200


def _public_exam_now():
    return vietnam_now_naive()


def _public_question(question_key):
    kind, raw_id = question_key.split("-", 1)
    if kind == "exam":
        question = db.session.get(ExamExercise, int(raw_id))
    elif kind == "chapter":
        question = db.session.get(Exercise, int(raw_id))
    else:
        question = None
    return question


def _public_question_data(question_key):
    question = _public_question(question_key)
    if not question:
        return None
    examples = question.sample_examples
    return {
        "id": question_key, "title": question.title, "description": question.description,
        "input_format": question.input_format, "output_format": question.output_format,
        "constraints": question.constraints,
        "sample_input": examples[0]["input"] if examples else "",
        "sample_output": examples[0]["output"] if examples else "",
        "sample_examples": examples,
    }


def _public_questions_for_session(session):
    keys = json.loads(session.question_ids or "[]")
    return [question for question in (_public_question_data(key) for key in keys) if question]


def _public_session_for_request(session_id):
    session = db.session.get(PublicExamSession, session_id)
    token = request.headers.get("X-Exam-Session-Token", "")
    if not session or not session.verify_token(token):
        return None
    return session


def _public_exam_deadline(session):
    deadline = session.started_at + timedelta(minutes=session.exam.duration_minutes)
    if session.exam.end_time:
        deadline = min(deadline, session.exam.end_time)
    return deadline


def _issue_public_session_token(session):
    raw_token = secrets.token_urlsafe(32)
    session.session_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token


def _grade_public_drafts(session):
    question_keys = json.loads(session.question_ids or "[]")
    for question_key in question_keys:
        submission = PublicExamSubmission.query.filter_by(
            session_id=session.id, question_key=question_key
        ).first()
        if not submission:
            submission = PublicExamSubmission(session_id=session.id, question_key=question_key, code="")
            db.session.add(submission)
        question = _public_question(question_key)
        if not question:
            continue
        result = evaluate_submission(
            student_code=submission.code,
            generator_code=question.generator_code,
            solution_code=question.solution_code,
            num_tests=question.num_test_cases,
        )
        submission.status = result["status"]
        submission.score = result["score"]
        submission.max_score = result["max_score"]


@public_exam_bp.route("/<access_code>", methods=["GET"])
def public_exam_info(access_code):
    exam = Exam.query.filter_by(access_code=access_code).first()
    if not exam:
        return _json_error("Không tìm thấy bài thi.", 404)
    now = _public_exam_now()
    return jsonify({
        "success": True, "name": exam.name,
        "start_time": vietnam_iso(exam.start_time),
        "is_open": not exam.start_time or now >= exam.start_time,
        "password_configured": bool(exam.password_hash),
    }), 200


@public_exam_bp.route("/<access_code>/start", methods=["POST"])
def start_public_exam(access_code):
    exam = Exam.query.filter_by(access_code=access_code).first()
    if not exam:
        return _json_error("Không tìm thấy bài thi.", 404)
    data = request.get_json(silent=True) or {}
    full_name = (data.get("full_name") or "").strip()
    student_id = (data.get("student_id") or "").strip()
    class_name = (data.get("class_name") or "").strip()
    password = data.get("password") or ""
    if not full_name or not student_id or not class_name:
        return _json_error("Vui lòng nhập họ tên, MSV và lớp.")
    if len(full_name) > 120 or len(student_id) > 50 or len(class_name) > 50:
        return _json_error("Thông tin sinh viên vượt quá độ dài cho phép.")

    now = _public_exam_now()
    if exam.start_time and now < exam.start_time:
        return _json_error("Chưa đến giờ thi. Mật khẩu phòng thi chưa được kích hoạt.", 403)
    if exam.end_time and now > exam.end_time:
        return _json_error("Bài thi đã đóng.", 403)
    if not exam.password_hash:
        return _json_error("Giáo viên chưa kích hoạt mật khẩu phòng thi.", 403)
    if not exam.check_exam_password(password):
        return _json_error("Mật khẩu bài thi không chính xác.", 403)

    sessions = PublicExamSession.query.filter_by(
        exam_id=exam.id, student_id=student_id
    ).order_by(PublicExamSession.attempt_number.desc()).all()
    for active in sessions:
        if active.full_name.casefold() != full_name.casefold() or active.class_name.casefold() != class_name.casefold():
            return _json_error("MSV này đã được đăng ký với họ tên hoặc lớp khác.", 403)
        if not active.is_finalized:
            if now < _public_exam_deadline(active):
                raw_token = _issue_public_session_token(active)
                db.session.commit()
                return jsonify({
                    "success": True, "session_id": active.id, "is_resumed": True,
                    "session_token": raw_token,
                }), 200
            _grade_public_drafts(active)
            active.is_finalized = True
            active.finished_at = now
            db.session.commit()

    if len(sessions) >= exam.max_attempts:
        if not sessions:
            return _json_error("Bạn đã hết lượt làm bài.", 403)
        latest = sessions[0]
        raw_token = _issue_public_session_token(latest)
        db.session.commit()
        return jsonify({
            "success": True, "session_id": latest.id, "read_only": True,
            "session_token": raw_token,
        }), 200

    question_keys = []
    rules = ExamChapterRule.query.filter_by(exam_id=exam.id).all()
    if rules:
        for rule in rules:
            available = Exercise.query.filter_by(chapter_id=rule.chapter_id, is_published=True).all()
            if rule.question_count > len(available):
                return _json_error("Ngân hàng câu hỏi đã thay đổi; giáo viên cần cập nhật số câu theo chương.", 409)
            question_keys.extend(f"chapter-{exercise.id}" for exercise in random.sample(available, rule.question_count))
    else:
        question_keys = [f"exam-{exercise.id}" for exercise in exam.exercises if exercise.is_published]
    if not question_keys:
        return _json_error("Bài thi chưa có câu hỏi được xuất bản.", 400)

    raw_token = secrets.token_urlsafe(32)
    attempt_number = len(sessions) + 1
    session = PublicExamSession(
        exam_id=exam.id, student_id=student_id, full_name=full_name, class_name=class_name,
        attempt_number=attempt_number, question_ids=json.dumps(question_keys),
        session_token_hash=hashlib.sha256(raw_token.encode("utf-8")).hexdigest(),
        started_at=now,
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({
        "success": True, "session_id": session.id, "is_resumed": False,
        "session_token": raw_token, "attempt_number": attempt_number,
    }), 201


@public_exam_bp.route("/sessions/<int:session_id>", methods=["GET"])
def get_public_exam_session(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    submissions = {item.question_key: item.to_dict() for item in session.submissions}
    remain_seconds = max(0, int((_public_exam_deadline(session) - _public_exam_now()).total_seconds()))
    if not session.is_finalized and remain_seconds <= 0:
        _grade_public_drafts(session)
        session.is_finalized = True
        session.finished_at = _public_exam_now()
        db.session.commit()
        submissions = {item.question_key: item.to_dict() for item in session.submissions}
    return jsonify({
        "success": True, "exam": {"name": session.exam.name, "exercises": _public_questions_for_session(session)},
        "submissions": submissions, "remain_seconds": remain_seconds,
        "read_only": session.is_finalized, "result": session.to_dict(),
    }), 200


@public_exam_bp.route("/sessions/<int:session_id>/save-draft", methods=["POST"])
def save_public_draft(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    if session.is_finalized or _public_exam_now() >= _public_exam_deadline(session):
        return _json_error("Phiên thi đã kết thúc.", 403)
    data = request.get_json(silent=True) or {}
    question_key, code = data.get("question_id"), data.get("code", "")
    if question_key not in json.loads(session.question_ids or "[]") or not isinstance(code, str):
        return _json_error("Câu hỏi hoặc mã nguồn không hợp lệ.")
    submission = PublicExamSubmission.query.filter_by(session_id=session.id, question_key=question_key).first()
    if not submission:
        submission = PublicExamSubmission(session_id=session.id, question_key=question_key)
        db.session.add(submission)
    submission.code = code
    db.session.commit()
    return jsonify({"success": True}), 200


@public_exam_bp.route("/sessions/<int:session_id>/submit", methods=["POST"])
def submit_public_answer(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    if session.is_finalized or _public_exam_now() >= _public_exam_deadline(session):
        return _json_error("Phiên thi đã kết thúc.", 403)
    data = request.get_json(silent=True) or {}
    question_key, code = data.get("question_id"), data.get("code", "")
    if question_key not in json.loads(session.question_ids or "[]") or not isinstance(code, str):
        return _json_error("Câu hỏi hoặc mã nguồn không hợp lệ.")
    question = _public_question(question_key)
    if not question:
        return _json_error("Không tìm thấy câu hỏi.", 404)
    result = evaluate_submission(code, question.generator_code, question.solution_code, question.num_test_cases)
    submission = PublicExamSubmission.query.filter_by(session_id=session.id, question_key=question_key).first()
    if not submission:
        submission = PublicExamSubmission(session_id=session.id, question_key=question_key)
        db.session.add(submission)
    submission.code = code
    submission.status = result["status"]
    submission.score = result["score"]
    submission.max_score = result["max_score"]
    db.session.commit()
    return jsonify({"success": True, "result": submission.to_dict()}), 200


@public_exam_bp.route("/sessions/<int:session_id>/finish", methods=["POST"])
def finish_public_exam(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    if not session.is_finalized:
        _grade_public_drafts(session)
        session.is_finalized = True
        session.finished_at = _public_exam_now()
        db.session.commit()
    return jsonify({
        "success": True, "result": session.to_dict(),
        "submissions": {item.question_key: item.to_dict() for item in session.submissions},
    }), 200


@public_exam_bp.route("/sessions/<int:session_id>/violation", methods=["POST"])
def record_public_violation(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    if session.is_finalized:
        return _json_error("Phiên thi đã kết thúc.", 403)
    session.violation_count += 1
    db.session.commit()
    return jsonify({"success": True, "violation_count": session.violation_count}), 200