import ast
from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from extensions import db
from models import (
    Chapter, Exercise, ChapterSession, ChapterSubmission, 
    Exam, ExamExercise, ExamSession, ExamSubmission, ExamChapterSubmission,
    ExamMonitoringRecord, ExamProctoringEvent,
    FreePracticeSession, FreePracticeSubmission,
    ExamRetakePermission,
    ExamChapterRule, PublicExamSession, PublicExamSubmission
)
from decorators import role_required
from exam_proctoring import add_event as add_proctoring_event, get_or_create_record
from judge import evaluate_submission, run_python_code
from time_utils import vietnam_iso, vietnam_local_naive, vietnam_now_naive
import random
import json
import hashlib
import math
import re
import secrets
from datetime import timedelta
from sqlalchemy.exc import IntegrityError
from time_utils import utc_now_naive

student_api_bp = Blueprint("student_api", __name__, url_prefix="/api/student")
public_exam_bp = Blueprint("public_exam", __name__, url_prefix="/api/public-exams")

def _json_error(msg, code=400):
    return jsonify({"success": False, "message": msg}), code


def _uses_sys_stdin(code):
    try:
        tree = ast.parse(code)
    except (SyntaxError, RecursionError):
        return False

    sys_modules = set()
    stdin_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            sys_modules.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "sys"
            )
        elif isinstance(node, ast.ImportFrom) and node.module == "sys":
            stdin_names.update(
                alias.asname or alias.name
                for alias in node.names
                if alias.name == "stdin"
            )

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "stdin"
            and isinstance(node.value, ast.Name)
            and node.value.id in sys_modules
        ):
            return True
        if isinstance(node, ast.Name) and node.id in stdin_names:
            return True
    return False


def _request_exam_device_id(data=None):
    value = request.headers.get("X-Exam-Device-Id")
    if value is None and isinstance(data, dict):
        value = data.get("device_id")
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._:-]{1,64}", value):
        raise ValueError("Mã thiết bị không hợp lệ.")
    return value


def _request_exam_device_id_for_session(session, data=None):
    if not session.exam.anti_cheat_enabled:
        return None
    return _request_exam_device_id(data)


def _exam_exit_event_for_token(record, session_id, event_token):
    if not event_token:
        return None
    return ExamProctoringEvent.query.filter(
        ExamProctoringEvent.record_id == record.id,
        ExamProctoringEvent.session_id == session_id,
        ExamProctoringEvent.event_type.in_(("focus_leave", "exam_resume")),
        ExamProctoringEvent.event_token == event_token,
    ).first()


def _exam_session_access_error(session, device_id=None):
    if not session.exam.anti_cheat_enabled:
        return None, None

    record = ExamMonitoringRecord.query.filter_by(
        exam_id=session.exam_id,
        user_id=session.user_id,
    ).first()
    if not record:
        return None, None

    if record.current_session_id == session.id:
        if record.is_blocked:
            return record, (
                jsonify({
                    "success": False,
                    "blocked": True,
                    "reason": "blocked",
                    "message": "Bài thi đã bị giáo viên đình chỉ.",
                }),
                423,
            )
        if record.device_id and device_id and record.device_id != device_id:
            return record, (
                jsonify({
                    "success": False,
                    "reason": "device_replaced",
                    "message": "Phiên thi này đang được sử dụng trên thiết bị khác. Hãy quay lại danh sách bài thi để tiếp tục.",
                }),
                409,
            )
    elif record.current_session_id and not session.is_finalized:
        return record, (
            jsonify({
                "success": False,
                "reason": "session_replaced",
                "message": "Phiên thi đã được thay thế. Hãy quay lại danh sách bài thi để tiếp tục.",
            }),
            409,
        )
    return record, None


def _request_exam_session_access_error(session):
    try:
        device_id = _request_exam_device_id_for_session(session)
    except ValueError as error:
        return _json_error(str(error))
    return _exam_session_access_error(session, device_id)[1]


def _run_custom_input(data):
    if not isinstance(data, dict):
        return None, _json_error("Dữ liệu chạy thử không hợp lệ.")
    code = data.get("code")
    input_data = data.get("input", "")
    if not isinstance(code, str) or not code.strip():
        return None, _json_error("Vui lòng nhập code trước khi chạy thử.")
    if not isinstance(input_data, str):
        return None, _json_error("Input phải là văn bản.")
    if len(code) > 50000:
        return None, _json_error("Code vượt quá giới hạn 50.000 ký tự.")
    if len(input_data) > 20000:
        return None, _json_error("Input vượt quá giới hạn 20.000 ký tự.")

    if not input_data and _uses_sys_stdin(code):
        return jsonify({
            "success": True,
            "stdout": "",
            "stderr": "",
            "output_truncated": False,
            "timed_out": False,
            "needs_input": True,
        }), None

    stdout, stderr = run_python_code(code, input_data, timeout=3)
    needs_input = stderr.rstrip().endswith(
        ("EOFError: EOF when reading a line", "EOFError: EOF when reading line")
    )
    if needs_input:
        stderr = ""
    return jsonify({
        "success": True,
        "stdout": stdout[:50000],
        "stderr": stderr[:10000],
        "output_truncated": len(stdout) > 50000 or len(stderr) > 10000,
        "timed_out": stderr == "Time Limit Exceeded",
        "needs_input": needs_input,
    }), None


# ============================================================
# PHẦN 1: LUYỆN TẬP CHƯƠNG
# ============================================================

@student_api_bp.route("/chapters", methods=["GET"])
@role_required("student")
def get_chapters():
    user_id = int(get_jwt_identity())
    chapters = Chapter.query.filter_by(is_hidden=False).order_by(
        Chapter.created_at.desc()
    ).all()
    
    sessions = ChapterSession.query.filter_by(user_id=user_id, is_finalized=True).all()
    
    chapter_scores = {}
    for s in sessions:
        if s.chapter_id not in chapter_scores:
            chapter_scores[s.chapter_id] = 0
        chapter_scores[s.chapter_id] = max(chapter_scores[s.chapter_id], s.to_dict()["total_score"])

    completed_by_chapter = dict(
        db.session.query(
            ChapterSession.chapter_id,
            db.func.count(db.distinct(ChapterSubmission.exercise_id)),
        )
        .join(ChapterSubmission, ChapterSubmission.session_id == ChapterSession.id)
        .join(Exercise, Exercise.id == ChapterSubmission.exercise_id)
        .filter(
            ChapterSession.user_id == user_id,
            ChapterSession.chapter_id == Exercise.chapter_id,
            ChapterSubmission.status == "correct",
            Exercise.is_published.is_(True),
        )
        .group_by(ChapterSession.chapter_id)
        .all()
    )

    result = []
    for c in chapters:
        result.append({
            "id": c.id,
            "name": c.name,
            "mode": c.mode,
            "total_exercises": len([ex for ex in c.exercises if ex.is_published]), # Chỉ đếm bài đã xuất bản
            "completed_exercises": completed_by_chapter.get(c.id, 0),
            "teacher_name": c.teacher.full_name or c.teacher.email,
            "best_score": chapter_scores.get(c.id, None)
        })

    return jsonify({"success": True, "chapters": result}), 200


@student_api_bp.route("/chapters/<int:cid>", methods=["GET"])
@role_required("student")
def get_chapter_detail(cid):
    user_id = int(get_jwt_identity())
    chapter = Chapter.query.get(cid)
    if not chapter or chapter.is_hidden:
        return _json_error("Không tìm thấy chương.", 404)

    active_session = ChapterSession.query.filter_by(
        user_id=user_id, chapter_id=cid, is_finalized=False
    ).order_by(ChapterSession.started_at.desc()).first()

    history_sessions = ChapterSession.query.filter_by(
        user_id=user_id, chapter_id=cid, is_finalized=True
    ).order_by(ChapterSession.finished_at.desc()).all()

    # ⭐ Chỉ lấy các bài được xuất bản
    exercises = [ex for ex in chapter.exercises if ex.is_published]
    
    ex_list = [ex.to_student_dict() for ex in exercises]

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
    if not chapter or chapter.is_hidden:
        return _json_error("Không tìm thấy chương.", 404)

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
    
    ex_list = [ex.to_student_dict() for ex in exercises]
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


@student_api_bp.route("/sessions/<int:sid>/run", methods=["POST"])
@role_required("student")
def run_chapter_code(sid):
    user_id = int(get_jwt_identity())
    session = ChapterSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên.", 404)
    if session.is_finalized:
        return _json_error("Phiên làm bài đã kết thúc.", 403)

    data = request.get_json(silent=True)
    exercise_id = data.get("exercise_id") if isinstance(data, dict) else None
    exercise = Exercise.query.filter_by(
        id=exercise_id,
        chapter_id=session.chapter_id,
        is_published=True,
    ).first()
    if not exercise:
        return _json_error("Không tìm thấy bài tập trong phiên này.", 404)

    result, error = _run_custom_input(data)
    return error if error else (result, 200)


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
    question_count = sum(
        1 for chapter_exercise in session.chapter.exercises
        if chapter_exercise.is_published
    )
    if not question_count:
        return _json_error("Chương này chưa có bài tập được công bố.", 400)

    # ⭐ GỌI MODULE CHẤM ĐIỂM TỰ ĐỘNG
    result = evaluate_submission(
        student_code=code,
        generator_code=exercise.generator_code,
        solution_code=exercise.solution_code,
        num_tests=exercise.num_test_cases,
        max_score=10.0 / question_count,
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


def _free_session_question_keys(session):
    try:
        question_keys = json.loads(session.question_ids or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(question_keys, list):
        return []
    return [
        key for key in question_keys
        if isinstance(key, str)
        and key.startswith("chapter-")
        and key.removeprefix("chapter-").isdecimal()
    ]


def _free_session_chapter_ids(session):
    try:
        chapter_ids = json.loads(session.chapter_ids or "[]")
    except (TypeError, ValueError):
        return []
    return chapter_ids if isinstance(chapter_ids, list) else []


def _free_question_for_session(question_key, session):
    if not isinstance(question_key, str) or not question_key.startswith("chapter-"):
        return None
    try:
        exercise_id = int(question_key.removeprefix("chapter-"))
    except ValueError:
        return None
    exercise = Exercise.query.filter_by(
        id=exercise_id,
        is_published=True,
    ).first()
    if not exercise or exercise.chapter_id not in _free_session_chapter_ids(session):
        return None
    return exercise


def _free_question_data(question_key, exercise):
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


def _free_session_is_expired(session):
    return (
        session.mode == "simulation"
        and session.duration_minutes is not None
        and vietnam_now_naive()
        >= session.started_at + timedelta(minutes=session.duration_minutes)
    )


def _grade_free_session_drafts(session):
    question_keys = _free_session_question_keys(session)
    if not question_keys:
        return
    max_score = 10.0 / len(question_keys)
    for question_key in question_keys:
        exercise = _free_question_for_session(question_key, session)
        if not exercise:
            continue
        submission = FreePracticeSubmission.query.filter_by(
            session_id=session.id,
            exercise_id=exercise.id,
        ).first()
        if not submission or not submission.code.strip():
            continue
        result = evaluate_submission(
            student_code=submission.code,
            generator_code=exercise.generator_code,
            solution_code=exercise.solution_code,
            num_tests=exercise.num_test_cases,
            max_score=max_score,
        )
        submission.status = result["status"]
        submission.score = result["score"]
        submission.max_score = result["max_score"]


def _finalize_free_session(session, auto_submit=False):
    if session.is_finalized:
        return
    if auto_submit:
        _grade_free_session_drafts(session)
    session.is_finalized = True
    session.finished_at = vietnam_now_naive()


def _free_session_submissions(session):
    submissions = {}
    for key in _free_session_question_keys(session):
        exercise = _free_question_for_session(key, session)
        if not exercise:
            continue
        submission = FreePracticeSubmission.query.filter_by(
            session_id=session.id,
            exercise_id=exercise.id,
        ).first()
        if submission:
            submissions[key] = submission.to_dict()
    return submissions


def _stratified_free_questions(question_groups, question_count):
    remaining_by_chapter = {
        chapter_id: list(exercises)
        for chapter_id, exercises in question_groups.items()
        if exercises
    }
    if sum(map(len, remaining_by_chapter.values())) < question_count:
        return []

    selected = []
    selected_per_chapter = {chapter_id: 0 for chapter_id in remaining_by_chapter}
    if len(remaining_by_chapter) >= question_count:
        for chapter_id in random.sample(list(remaining_by_chapter), question_count):
            selected.append(random.choice(remaining_by_chapter[chapter_id]))
    else:
        for chapter_id, questions in remaining_by_chapter.items():
            question = random.choice(questions)
            questions.remove(question)
            selected.append(question)
            selected_per_chapter[chapter_id] = 1

        while len(selected) < question_count:
            eligible_chapters = [
                chapter_id
                for chapter_id, questions in remaining_by_chapter.items()
                if questions
            ]
            fewest_selected = min(
                selected_per_chapter[chapter_id]
                for chapter_id in eligible_chapters
            )
            least_used_chapters = [
                chapter_id
                for chapter_id in eligible_chapters
                if selected_per_chapter[chapter_id] == fewest_selected
            ]
            chapter_id = random.choice(least_used_chapters)
            question = random.choice(remaining_by_chapter[chapter_id])
            remaining_by_chapter[chapter_id].remove(question)
            selected.append(question)
            selected_per_chapter[chapter_id] += 1

    random.shuffle(selected)
    return selected


@student_api_bp.route("/free-sessions/start", methods=["POST"])
@role_required("student")
def start_free_session():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu phiên luyện tập không hợp lệ.")

    mode = data.get("mode")
    if mode not in ("practice", "simulation"):
        return _json_error("Chế độ luyện tập không hợp lệ.")
    raw_chapter_ids = data.get("chapter_ids")
    if (
        not isinstance(raw_chapter_ids, list)
        or not raw_chapter_ids
        or any(type(chapter_id) is not int for chapter_id in raw_chapter_ids)
    ):
        return _json_error("Vui lòng chọn chương hợp lệ.")
    chapter_ids = list(dict.fromkeys(raw_chapter_ids))
    if mode == "practice" and len(chapter_ids) != 1:
        return _json_error("Chế độ luyện tập chỉ cho phép chọn một chương.")

    chapters = Chapter.query.filter(Chapter.id.in_(chapter_ids)).all()
    if len(chapters) != len(chapter_ids):
        return _json_error("Không tìm thấy một hoặc nhiều chương đã chọn.", 404)
    if any(chapter.is_hidden for chapter in chapters):
        return _json_error("Một hoặc nhiều chương hiện đang bị ẩn.", 404)

    question_count = data.get("question_count")
    if type(question_count) is not int or question_count < 1:
        return _json_error("Số câu hỏi phải là số nguyên lớn hơn 0.")

    question_groups = {
        chapter_id: Exercise.query.filter_by(
            chapter_id=chapter_id,
            is_published=True,
        ).all()
        for chapter_id in chapter_ids
    }
    total_available = sum(len(exercises) for exercises in question_groups.values())
    if question_count > total_available:
        return _json_error(
            f"Số câu hỏi tối đa trong phạm vi đã chọn là {total_available}."
        )

    duration_minutes = None
    if mode == "practice":
        questions = random.sample(question_groups[chapter_ids[0]], question_count)
    else:
        raw_duration = data.get("duration_minutes")
        if (
            isinstance(raw_duration, bool)
            or not isinstance(raw_duration, (int, float))
        ):
            return _json_error("Thời gian làm bài phải lớn hơn 0 phút.")
        try:
            duration_minutes = float(raw_duration)
            vietnam_now_naive() + timedelta(minutes=duration_minutes)
        except (OverflowError, ValueError):
            return _json_error("Thời gian làm bài vượt quá giới hạn hợp lệ.")
        if not math.isfinite(duration_minutes) or duration_minutes <= 0:
            return _json_error("Thời gian làm bài phải lớn hơn 0 phút.")
        questions = _stratified_free_questions(question_groups, question_count)

    if len(questions) != question_count:
        return _json_error("Không đủ câu hỏi duy nhất trong phạm vi đã chọn.")

    question_keys = [f"chapter-{exercise.id}" for exercise in questions]
    session = FreePracticeSession(
        user_id=user_id,
        mode=mode,
        chapter_ids=json.dumps(chapter_ids),
        question_ids=json.dumps(question_keys),
        duration_minutes=duration_minutes,
    )
    db.session.add(session)
    db.session.commit()
    return jsonify({"success": True, "session_id": session.id}), 201


@student_api_bp.route("/free-sessions/<int:sid>", methods=["GET"])
@role_required("student")
def get_free_session(sid):
    user_id = int(get_jwt_identity())
    session = FreePracticeSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên luyện tập.", 404)

    remain_seconds = None
    if session.mode == "simulation":
        remain_seconds = max(0, int((
            session.started_at + timedelta(minutes=session.duration_minutes)
            - vietnam_now_naive()
        ).total_seconds()))
        if remain_seconds <= 0:
            _finalize_free_session(session, auto_submit=True)
            db.session.commit()

    exercises = []
    for key in _free_session_question_keys(session):
        exercise = _free_question_for_session(key, session)
        if exercise:
            exercises.append(_free_question_data(key, exercise))
    if not exercises:
        return _json_error("Phiên luyện tập không còn câu hỏi khả dụng.", 409)

    return jsonify({
        "success": True,
        "exam": {
            "id": 0,
            "name": "Luyện tập tự do" if session.mode == "practice" else "Ôn thi tự do",
            "exercises": exercises,
        },
        "submissions": _free_session_submissions(session),
        "remain_seconds": remain_seconds,
        "read_only": session.is_finalized,
        "result": session.to_dict(),
    }), 200


@student_api_bp.route("/free-sessions/<int:sid>/save-draft", methods=["POST"])
@role_required("student")
def save_free_draft(sid):
    user_id = int(get_jwt_identity())
    session = FreePracticeSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên luyện tập.", 404)
    if session.is_finalized or _free_session_is_expired(session):
        if not session.is_finalized:
            _finalize_free_session(session, auto_submit=True)
            db.session.commit()
        return _json_error("Phiên luyện tập đã kết thúc.", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu lưu nháp không hợp lệ.")
    question_key = _exam_question_key_from_request(
        data.get("exercise_id"),
        _free_session_question_keys(session),
    )
    code = data.get("code")
    if not question_key or not isinstance(code, str):
        return _json_error("Câu hỏi hoặc mã nguồn không hợp lệ.")
    exercise = _free_question_for_session(question_key, session)
    if not exercise:
        return _json_error("Không tìm thấy câu hỏi trong phiên này.", 404)

    submission = FreePracticeSubmission.query.filter_by(
        session_id=session.id,
        exercise_id=exercise.id,
    ).first()
    if not submission:
        submission = FreePracticeSubmission(
            session_id=session.id,
            exercise_id=exercise.id,
        )
        db.session.add(submission)
    submission.code = code
    db.session.commit()
    return jsonify({"success": True}), 200


@student_api_bp.route("/free-sessions/<int:sid>/run", methods=["POST"])
@role_required("student")
def run_free_code(sid):
    user_id = int(get_jwt_identity())
    session = FreePracticeSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên luyện tập.", 404)
    if session.is_finalized or _free_session_is_expired(session):
        if not session.is_finalized:
            _finalize_free_session(session, auto_submit=True)
            db.session.commit()
        return _json_error("Phiên luyện tập đã kết thúc.", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu chạy thử không hợp lệ.")
    question_key = _exam_question_key_from_request(
        data.get("exercise_id"),
        _free_session_question_keys(session),
    )
    if not question_key or not _free_question_for_session(question_key, session):
        return _json_error("Không tìm thấy câu hỏi trong phiên này.", 404)

    result, error = _run_custom_input(data)
    return error if error else (result, 200)


@student_api_bp.route("/free-sessions/<int:sid>/submit", methods=["POST"])
@role_required("student")
def submit_free_answer(sid):
    user_id = int(get_jwt_identity())
    session = FreePracticeSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên luyện tập.", 404)
    if session.is_finalized or _free_session_is_expired(session):
        if not session.is_finalized:
            _finalize_free_session(session, auto_submit=True)
            db.session.commit()
        return _json_error("Phiên luyện tập đã kết thúc.", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu nộp bài không hợp lệ.")
    question_keys = _free_session_question_keys(session)
    question_key = _exam_question_key_from_request(
        data.get("exercise_id"),
        question_keys,
    )
    code = data.get("code")
    if not question_key or not isinstance(code, str):
        return _json_error("Câu hỏi hoặc mã nguồn không hợp lệ.")
    exercise = _free_question_for_session(question_key, session)
    if not exercise:
        return _json_error("Không tìm thấy câu hỏi trong phiên này.", 404)

    result = evaluate_submission(
        student_code=code,
        generator_code=exercise.generator_code,
        solution_code=exercise.solution_code,
        num_tests=exercise.num_test_cases,
        max_score=10.0 / len(question_keys),
    )
    submission = FreePracticeSubmission.query.filter_by(
        session_id=session.id,
        exercise_id=exercise.id,
    ).first()
    if not submission:
        submission = FreePracticeSubmission(
            session_id=session.id,
            exercise_id=exercise.id,
        )
        db.session.add(submission)
    submission.code = code
    submission.status = result["status"]
    submission.score = result["score"]
    submission.max_score = result["max_score"]
    db.session.commit()
    return jsonify({"success": True, "result": submission.to_dict()}), 200


@student_api_bp.route("/free-sessions/<int:sid>/finish", methods=["POST"])
@role_required("student")
def finish_free_session(sid):
    user_id = int(get_jwt_identity())
    session = FreePracticeSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên luyện tập.", 404)
    data = request.get_json(silent=True) or {}
    _finalize_free_session(
        session,
        auto_submit=(
            session.mode == "simulation"
            and isinstance(data, dict)
            and (
                _free_session_is_expired(session)
                or data.get("auto_submit") is True
            )
        ),
    )
    db.session.commit()
    return jsonify({
        "success": True,
        "result": session.to_dict(),
        "submissions": _free_session_submissions(session),
    }), 200


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


@student_api_bp.route("/exams/active-session", methods=["POST"])
@role_required("student")
def resume_active_exam():
    user_id = int(get_jwt_identity())
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _json_error("Dữ liệu khôi phục bài thi không hợp lệ.")
    prior_focus_event_token = data.get("prior_focus_event_token")
    now = vietnam_now_naive()
    sessions = ExamSession.query.filter_by(
        user_id=user_id,
        is_finalized=False,
    ).order_by(ExamSession.started_at.desc(), ExamSession.id.desc()).all()

    for session in sessions:
        anti_cheat_enabled = session.exam.anti_cheat_enabled
        device_id = None
        if anti_cheat_enabled:
            try:
                device_id = _request_exam_device_id(data)
            except ValueError as error:
                return _json_error(str(error))
            if not device_id:
                return _json_error("Thiếu mã thiết bị.", 400)
            if prior_focus_event_token is not None and (
                not isinstance(prior_focus_event_token, str)
                or not re.fullmatch(r"[a-f0-9]{32}", prior_focus_event_token)
            ):
                return _json_error("Mã sự kiện rời màn hình không hợp lệ.")

        deadline = session.started_at + timedelta(
            minutes=session.exam.duration_minutes
        )
        if session.exam.end_time:
            deadline = min(deadline, vietnam_local_naive(session.exam.end_time))
        if now >= deadline:
            continue

        record = None
        if anti_cheat_enabled:
            record = ExamMonitoringRecord.query.filter_by(
                exam_id=session.exam_id,
                user_id=user_id,
            ).first()
            if record and record.is_blocked:
                continue

        question_keys, message, status = _exam_session_question_keys(session)
        if message:
            return _json_error(message, status)

        session.question_ids = json.dumps(question_keys)
        if not anti_cheat_enabled:
            db.session.commit()
            return jsonify({
                "success": True,
                "active": True,
                "session_id": session.id,
                "exam_id": session.exam_id,
                "anti_cheat_enabled": False,
                "abnormal_count": 0,
                "device_changed": False,
            }), 200

        record = get_or_create_record(
            exam_id=session.exam_id,
            user_id=user_id,
            session_id=session.id,
            device_id=device_id,
        )
        device_changed = bool(record.device_id and record.device_id != device_id)
        previous_exit_event = _exam_exit_event_for_token(
            record,
            session.id,
            prior_focus_event_token,
        )

        if device_id:
            record.device_id = device_id
        record.current_session_id = session.id
        if not previous_exit_event:
            token_marker = (
                f" (event_token={prior_focus_event_token})"
                if prior_focus_event_token else ""
            )
            add_proctoring_event(
                record,
                "exam_resume",
                "Tắt tab hoặc đăng nhập lại phiên mới khi đang làm bài"
                + token_marker,
                session_id=session.id,
                abnormal=True,
                event_token=prior_focus_event_token,
            )
        try:
            db.session.commit()
        except IntegrityError:
            if not prior_focus_event_token:
                raise
            db.session.rollback()
            record = ExamMonitoringRecord.query.filter_by(
                exam_id=session.exam_id,
                user_id=user_id,
            ).first()
            previous_exit_event = _exam_exit_event_for_token(
                record,
                session.id,
                prior_focus_event_token,
            )
            if not previous_exit_event:
                raise
            record.device_id = device_id
            record.current_session_id = session.id
            db.session.commit()
        return jsonify({
            "success": True,
            "active": True,
            "session_id": session.id,
            "exam_id": session.exam_id,
            "anti_cheat_enabled": True,
            "abnormal_count": record.abnormal_count,
            "device_changed": device_changed,
        }), 200

    return jsonify({"success": True, "active": False}), 200


@student_api_bp.route("/exams/<int:eid>/start", methods=["POST"])
@role_required("student")
def start_exam(eid):
    user_id = int(get_jwt_identity())
    exam = Exam.query.get(eid)
    if not exam: return _json_error("Không tìm thấy bài kiểm tra.", 404)

    now = vietnam_now_naive()
    start_time = vietnam_local_naive(exam.start_time) if exam.start_time else None
    end_time = vietnam_local_naive(exam.end_time) if exam.end_time else None
    if start_time and now < start_time:
        return _json_error("Chưa đến giờ làm bài.", 403)
    if end_time and now > end_time:
        return _json_error("Đã hết thời gian làm bài.", 403)

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return _json_error("Dữ liệu yêu cầu không hợp lệ.")
    device_id = None
    if exam.anti_cheat_enabled:
        try:
            device_id = _request_exam_device_id(data)
        except ValueError as error:
            return _json_error(str(error))
    password = data.get("password", "")
    if not isinstance(password, str):
        return _json_error("Mật khẩu bài thi không hợp lệ.")
    if exam.password_hash and not exam.check_exam_password(password):
        return _json_error("Mật khẩu bài thi không chính xác.", 403)

    monitoring = None
    if exam.anti_cheat_enabled:
        monitoring = ExamMonitoringRecord.query.filter_by(
            exam_id=eid,
            user_id=user_id,
        ).first()
        if monitoring and monitoring.is_blocked:
            return jsonify({
                "success": False,
                "blocked": True,
                "reason": "blocked",
                "message": "Bài thi đã bị giáo viên đình chỉ.",
            }), 423

    old = ExamSession.query.filter_by(user_id=user_id, exam_id=eid, is_finalized=False).first()
    if old:
        allowed_end_t = old.started_at + timedelta(minutes=exam.duration_minutes)
        if end_time:
            allowed_end_t = min(allowed_end_t, end_time)
            
        if now < allowed_end_t:
            question_keys, message, status = _exam_session_question_keys(old)
            if message:
                return _json_error(message, status)
            old.question_ids = json.dumps(question_keys)
            device_changed = False
            abnormal_count = 0
            if exam.anti_cheat_enabled:
                monitoring = get_or_create_record(
                    exam_id=eid,
                    user_id=user_id,
                    session_id=old.id,
                    device_id=device_id,
                )
                device_changed = bool(
                    monitoring.device_id and device_id
                    and monitoring.device_id != device_id
                )
                if device_changed:
                    add_proctoring_event(
                        monitoring,
                        "device_change",
                        "Đăng nhập thêm ở thiết bị khác",
                        session_id=old.id,
                        abnormal=True,
                    )
                if device_id:
                    monitoring.device_id = device_id
                monitoring.current_session_id = old.id
                abnormal_count = monitoring.abnormal_count
            db.session.commit()
            return jsonify({
                "success": True,
                "session_id": old.id,
                "is_resumed": True,
                "anti_cheat_enabled": exam.anti_cheat_enabled,
                "device_changed": device_changed,
                "abnormal_count": abnormal_count,
            }), 200
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
    db.session.flush()
    abnormal_count = 0
    if exam.anti_cheat_enabled:
        monitoring = get_or_create_record(
            exam_id=eid,
            user_id=user_id,
            session_id=new_sess.id,
            device_id=device_id,
        )
        monitoring.current_session_id = new_sess.id
        if device_id:
            monitoring.device_id = device_id
        abnormal_count = monitoring.abnormal_count
    db.session.commit()
    return jsonify({
        "success": True,
        "session_id": new_sess.id,
        "is_resumed": False,
        "anti_cheat_enabled": exam.anti_cheat_enabled,
        "device_changed": False,
        "abnormal_count": abnormal_count,
    }), 201


@student_api_bp.route("/exam-sessions/<int:sid>", methods=["GET"])
@role_required("student")
def get_exam_session(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Không tìm thấy phiên làm bài.", 404)
    try:
        device_id = _request_exam_device_id_for_session(session)
    except ValueError as error:
        return _json_error(str(error))
    _, access_error = _exam_session_access_error(session, device_id)
    if access_error:
        return access_error

    exam = session.exam
    now = vietnam_now_naive()

    end_time = vietnam_local_naive(exam.end_time) if exam.end_time else None
    if end_time and now > end_time:
        return _json_error("Đã hết thời gian làm bài.", 403)
        
    allowed_end_t = session.started_at + timedelta(minutes=exam.duration_minutes)
    if end_time:
        allowed_end_t = min(allowed_end_t, end_time)

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
            "anti_cheat_enabled": exam.anti_cheat_enabled,
            "exercises": ex_list
        },
        "submissions": subs,
        "remain_seconds": remain_seconds,
        "abnormal_count": (
            ExamMonitoringRecord.query.filter_by(
                exam_id=session.exam_id,
                user_id=session.user_id,
            ).with_entities(ExamMonitoringRecord.abnormal_count).scalar() or 0
        ) if exam.anti_cheat_enabled else 0,
    }), 200


@student_api_bp.route("/exam-sessions/<int:sid>/status", methods=["GET"])
@role_required("student")
def get_exam_session_status(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên làm bài.", 404)
    try:
        device_id = _request_exam_device_id_for_session(session)
    except ValueError as error:
        return _json_error(str(error))
    record, access_error = _exam_session_access_error(session, device_id)
    if access_error:
        response, status = access_error
        if status != 423:
            return response, status
    return jsonify({
        "success": True,
        "anti_cheat_enabled": session.exam.anti_cheat_enabled,
        "is_blocked": bool(record and record.is_blocked),
        "is_cheating": bool(record and record.is_cheating),
        "abnormal_count": record.abnormal_count if record else 0,
        "is_finalized": session.is_finalized,
    }), 200


@student_api_bp.route("/exam-sessions/<int:sid>/abnormal-event", methods=["POST"])
@role_required("student")
def record_exam_abnormal_event(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Không tìm thấy phiên làm bài.", 404)
    if session.is_finalized:
        return _json_error("Bài thi đã kết thúc.", 403)
    now = vietnam_now_naive()
    deadline = session.started_at + timedelta(minutes=session.exam.duration_minutes)
    if session.exam.end_time:
        deadline = min(deadline, vietnam_local_naive(session.exam.end_time))
    if now >= deadline:
        return _json_error("Bài thi đã hết giờ.", 403)
    if not session.exam.anti_cheat_enabled:
        return jsonify({
            "success": True,
            "ignored": True,
            "abnormal_count": 0,
            "is_cheating": False,
        }), 200
    try:
        device_id = _request_exam_device_id_for_session(session)
    except ValueError as error:
        return _json_error(str(error))
    if not device_id:
        return _json_error("Thiếu mã thiết bị.", 400)

    record = ExamMonitoringRecord.query.filter_by(
        exam_id=session.exam_id,
        user_id=session.user_id,
    ).first()
    _, access_error = _exam_session_access_error(session, device_id)
    if access_error:
        return access_error
    if not record:
        record = get_or_create_record(
            exam_id=session.exam_id,
            user_id=session.user_id,
            session_id=session.id,
            device_id=device_id,
        )
    if record.current_session_id != session.id:
        return _json_error("Phiên thi đã được thay thế.", 409)
    if not record.device_id:
        record.device_id = device_id

    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict) or data.get("event_type") != "focus_leave":
        return _json_error("Loại hành vi bất thường không hợp lệ.")
    event_token = data.get("event_token")
    if event_token is not None and (
        not isinstance(event_token, str)
        or not re.fullmatch(r"[a-f0-9]{32}", event_token)
    ):
        return _json_error("Mã sự kiện rời màn hình không hợp lệ.")
    prior_event = _exam_exit_event_for_token(record, session.id, event_token)
    if prior_event:
        return jsonify({
            "success": True,
            "event_id": prior_event.id,
            "event_token": event_token,
            "abnormal_count": record.abnormal_count,
            "is_cheating": record.is_cheating,
            "deduplicated": True,
        }), 200

    detail = "Rời màn hình thi"
    if event_token:
        detail += f" (event_token={event_token})"
    event = add_proctoring_event(
        record,
        "focus_leave",
        detail,
        session_id=session.id,
        abnormal=True,
        event_token=event_token,
    )
    try:
        db.session.commit()
    except IntegrityError:
        if not event_token:
            raise
        db.session.rollback()
        record = ExamMonitoringRecord.query.filter_by(
            exam_id=session.exam_id,
            user_id=user_id,
        ).first()
        prior_event = _exam_exit_event_for_token(
            record,
            session.id,
            event_token,
        )
        if not prior_event:
            raise
        return jsonify({
            "success": True,
            "event_id": prior_event.id,
            "event_token": event_token,
            "abnormal_count": record.abnormal_count,
            "is_cheating": record.is_cheating,
            "deduplicated": True,
        }), 200
    return jsonify({
        "success": True,
        "event_id": event.id,
        "event_token": event_token,
        "abnormal_count": record.abnormal_count,
        "is_cheating": record.is_cheating,
    }), 200


@student_api_bp.route("/exam-sessions/<int:sid>/save-draft", methods=["POST"])
@role_required("student")
def save_exam_draft(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Lỗi phiên làm bài.", 404)
    access_error = _request_exam_session_access_error(session)
    if access_error:
        return access_error
    
    end_time = (
        vietnam_local_naive(session.exam.end_time)
        if session.exam.end_time else None
    )
    if end_time and vietnam_now_naive() > end_time:
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
    access_error = _request_exam_session_access_error(session)
    if access_error:
        return access_error

    end_time = (
        vietnam_local_naive(session.exam.end_time)
        if session.exam.end_time else None
    )
    if end_time and vietnam_now_naive() > end_time:
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
        num_tests=exercise.num_test_cases,
        max_score=10.0 / len(question_keys),
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


@student_api_bp.route("/exam-sessions/<int:sid>/run", methods=["POST"])
@role_required("student")
def run_exam_code(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session:
        return _json_error("Lỗi phiên làm bài.", 404)
    access_error = _request_exam_session_access_error(session)
    if access_error:
        return access_error
    if session.is_finalized:
        return _json_error("Bài thi đã kết thúc.", 403)

    end_time = (
        vietnam_local_naive(session.exam.end_time)
        if session.exam.end_time else None
    )
    if end_time and vietnam_now_naive() >= end_time:
        return _json_error("Đã hết giờ, không thể chạy thử.", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu chạy thử không hợp lệ.")
    question_keys, message, status = _exam_session_question_keys(session)
    if message:
        return _json_error(message, status)
    question_key = _exam_question_key_from_request(data.get("exercise_id"), question_keys)
    exercise, _ = _resolve_exam_question(question_key, session.exam)
    if not exercise:
        return _json_error("Không tìm thấy câu hỏi trong phiên này.", 404)

    result, error = _run_custom_input(data)
    return error if error else (result, 200)


@student_api_bp.route("/exam-sessions/<int:sid>/finish", methods=["POST"])
@role_required("student")
def finish_exam(sid):
    user_id = int(get_jwt_identity())
    session = ExamSession.query.filter_by(id=sid, user_id=user_id).first()
    if not session: return _json_error("Lỗi phiên làm bài.", 404)
    access_error = _request_exam_session_access_error(session)
    if access_error:
        return access_error

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
        deadline = min(deadline, vietnam_local_naive(session.exam.end_time))
    return deadline


def _issue_public_session_token(session):
    raw_token = secrets.token_urlsafe(32)
    session.session_token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    return raw_token


def _grade_public_drafts(session):
    question_keys = json.loads(session.question_ids or "[]")
    if not question_keys:
        return
    max_score = 10.0 / len(question_keys)
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
            max_score=max_score,
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
        "is_open": (
            not exam.start_time
            or now >= vietnam_local_naive(exam.start_time)
        ),
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
    start_time = vietnam_local_naive(exam.start_time) if exam.start_time else None
    end_time = vietnam_local_naive(exam.end_time) if exam.end_time else None
    if start_time and now < start_time:
        return _json_error("Chưa đến giờ thi. Mật khẩu phòng thi chưa được kích hoạt.", 403)
    if end_time and now > end_time:
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
    result = session.to_dict()
    if not session.exam.anti_cheat_enabled:
        result["violation_count"] = 0
    return jsonify({
        "success": True, "exam": {
            "name": session.exam.name,
            "anti_cheat_enabled": session.exam.anti_cheat_enabled,
            "exercises": _public_questions_for_session(session),
        },
        "submissions": submissions, "remain_seconds": remain_seconds,
        "read_only": session.is_finalized, "result": result,
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
    question_count = len(json.loads(session.question_ids or "[]"))
    if not question_count:
        return _json_error("Bài thi chưa có câu hỏi.", 400)
    result = evaluate_submission(
        code,
        question.generator_code,
        question.solution_code,
        question.num_test_cases,
        max_score=10.0 / question_count,
    )
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


@public_exam_bp.route("/sessions/<int:session_id>/run", methods=["POST"])
def run_public_answer(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    if session.is_finalized or _public_exam_now() >= _public_exam_deadline(session):
        return _json_error("Phiên thi đã kết thúc.", 403)

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _json_error("Dữ liệu chạy thử không hợp lệ.")
    question_key = data.get("question_id")
    if question_key not in json.loads(session.question_ids or "[]"):
        return _json_error("Câu hỏi không thuộc phiên thi này.")
    question = _public_question(question_key)
    if not question:
        return _json_error("Không tìm thấy câu hỏi.", 404)

    result, error = _run_custom_input(data)
    return error if error else (result, 200)


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
    result = session.to_dict()
    if not session.exam.anti_cheat_enabled:
        result["violation_count"] = 0
    return jsonify({
        "success": True, "result": result,
        "submissions": {item.question_key: item.to_dict() for item in session.submissions},
    }), 200


@public_exam_bp.route("/sessions/<int:session_id>/violation", methods=["POST"])
def record_public_violation(session_id):
    session = _public_session_for_request(session_id)
    if not session:
        return _json_error("Phiên thi không hợp lệ.", 401)
    if session.is_finalized:
        return _json_error("Phiên thi đã kết thúc.", 403)
    if not session.exam.anti_cheat_enabled:
        return jsonify({"success": True, "ignored": True, "violation_count": 0}), 200
    session.violation_count += 1
    db.session.commit()
    return jsonify({"success": True, "violation_count": session.violation_count}), 200