from flask import Blueprint, request, jsonify
from flask_jwt_extended import get_jwt_identity
from extensions import db
from models import (
    Chapter, Exercise, ChapterSession, ChapterSubmission,
    ExamChapterRule, ExamChapterSubmission
)
from decorators import role_required
from sample_cases import sample_fields_from_payload

chapters_bp = Blueprint("chapters", __name__, url_prefix="/api/chapters")

def _json_error(msg, code=400):
    return jsonify({"success": False, "message": msg}), code

# ============================================================
# 1. DANH SÁCH CHƯƠNG (Dành cho Giáo viên)
# ============================================================
@chapters_bp.route("", methods=["GET"])
@role_required("teacher")
def list_chapters():
    teacher_id = int(get_jwt_identity())
    chapters = Chapter.query.filter_by(teacher_id=teacher_id).order_by(Chapter.created_at.desc()).all()
    return jsonify({"success": True, "chapters": [c.to_dict(include_exercises=True, exercises_brief=True) for c in chapters]}), 200

# ============================================================
# 2. CHI TIẾT CHƯƠNG
# ============================================================
@chapters_bp.route("/<int:cid>", methods=["GET"])
@role_required("teacher")
def get_chapter(cid):
    teacher_id = int(get_jwt_identity())
    c = Chapter.query.filter_by(id=cid, teacher_id=teacher_id).first()
    if not c: return _json_error("Không tìm thấy chương.", 404)
    return jsonify({"success": True, "chapter": c.to_dict(include_exercises=True)}), 200

# ============================================================
# 3. TẠO CHƯƠNG MỚI (Mặc định Luyện tập)
# ============================================================
@chapters_bp.route("", methods=["POST"])
@role_required("teacher")
def create_chapter():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name or len(name) < 3:
        return _json_error("Tên chương phải có ít nhất 3 ký tự.")
    
    chapter = Chapter(name=name, mode="practice", teacher_id=int(get_jwt_identity()))
    db.session.add(chapter)
    db.session.commit()
    return jsonify({"success": True, "message": "Đã tạo chương.", "chapter": chapter.to_dict(include_exercises=True, exercises_brief=True)}), 201

# ============================================================
# 4. SỬA CHƯƠNG (Cài đặt chế độ)
# ============================================================
@chapters_bp.route("/<int:cid>", methods=["PUT"])
@role_required("teacher")
def update_chapter(cid):
    teacher_id = int(get_jwt_identity())
    c = Chapter.query.filter_by(id=cid, teacher_id=teacher_id).first()
    if not c: return _json_error("Không tìm thấy chương.", 404)

    data = request.get_json(silent=True) or {}
    if "name" in data:
        name = (data.get("name") or "").strip()
        if len(name) < 3: return _json_error("Tên chương phải từ 3 ký tự.")
        c.name = name

    c.mode = "practice"

    db.session.commit()
    return jsonify({"success": True, "message": "Đã cập nhật chương.", "chapter": c.to_dict(include_exercises=True, exercises_brief=True)}), 200


@chapters_bp.route("/<int:cid>/toggle-visibility", methods=["POST"])
@role_required("teacher")
def toggle_chapter_visibility(cid):
    chapter = Chapter.query.filter_by(
        id=cid,
        teacher_id=int(get_jwt_identity()),
    ).first()
    if not chapter:
        return _json_error("Không tìm thấy chương.", 404)

    chapter.is_hidden = not chapter.is_hidden
    db.session.commit()
    message = "Đã ẩn chương khỏi sinh viên." if chapter.is_hidden else "Đã hiện chương cho sinh viên."
    return jsonify({
        "success": True,
        "is_hidden": chapter.is_hidden,
        "message": message,
    }), 200


# ============================================================
# 5. XOÁ CHƯƠNG
# ============================================================
@chapters_bp.route("/<int:cid>", methods=["DELETE"])
@role_required("teacher")
def delete_chapter(cid):
    c = Chapter.query.filter_by(id=cid, teacher_id=int(get_jwt_identity())).first()
    if not c: return _json_error("Không tìm thấy chương.", 404)

    # 1. Xóa bài nộp liên quan đến các bài tập trong chương này trước
    exercise_ids = [ex.id for ex in Exercise.query.filter_by(chapter_id=c.id).all()]
    if exercise_ids:
        ChapterSubmission.query.filter(ChapterSubmission.exercise_id.in_(exercise_ids)).delete(synchronize_session=False)
        ExamChapterSubmission.query.filter(ExamChapterSubmission.exercise_id.in_(exercise_ids)).delete(synchronize_session=False)

    # 2. Xóa các phiên luyện tập thuộc chương này
    session_ids = [s.id for s in ChapterSession.query.filter_by(chapter_id=c.id).all()]
    if session_ids:
        ChapterSubmission.query.filter(ChapterSubmission.session_id.in_(session_ids)).delete(synchronize_session=False)
        ChapterSession.query.filter(ChapterSession.id.in_(session_ids)).delete(synchronize_session=False)

    # 3. Xóa quy tắc lấy đề từ chương (nếu có) và toàn bộ bài tập của chương
    ExamChapterRule.query.filter_by(chapter_id=c.id).delete(synchronize_session=False)
    Exercise.query.filter_by(chapter_id=c.id).delete(synchronize_session=False)

    # 4. Xóa chương chính
    db.session.delete(c)
    db.session.commit()
    return jsonify({"success": True, "message": "Đã xoá chương."}), 200

# ============================================================
# 6. THÊM BÀI TẬP VÀO CHƯƠNG (Đã cập nhật cấu trúc mới)
# ============================================================
@chapters_bp.route("/<int:cid>/exercises", methods=["POST"])
@role_required("teacher")
def create_exercise(cid):
    c = Chapter.query.filter_by(id=cid, teacher_id=int(get_jwt_identity())).first()
    if not c: return _json_error("Không tìm thấy chương.", 404)

    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()
    if len(title) < 3: return _json_error("Tên bài tập phải từ 3 ký tự.")
    try:
        sample_input, sample_output = sample_fields_from_payload(data)
    except ValueError as error:
        return _json_error(str(error))
    
    ex = Exercise(
        chapter_id=c.id, 
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
# 7. SỬA BÀI TẬP (Đã cập nhật cấu trúc mới)
# ============================================================
@chapters_bp.route("/exercises/<int:eid>", methods=["PUT"])
@role_required("teacher")
def update_exercise(eid):
    ex = Exercise.query.get(eid)
    if not ex or ex.chapter.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)

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
# 8. XOÁ BÀI TẬP
# ============================================================
@chapters_bp.route("/exercises/<int:eid>", methods=["DELETE"])
@role_required("teacher")
def delete_exercise(eid):
    ex = Exercise.query.get(eid)
    if not ex or ex.chapter.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)

    # Xóa các bài nộp trỏ tới bài tập này trước
    ChapterSubmission.query.filter_by(exercise_id=ex.id).delete(synchronize_session=False)
    ExamChapterSubmission.query.filter_by(exercise_id=ex.id).delete(synchronize_session=False)

    db.session.delete(ex)
    db.session.commit()
    return jsonify({"success": True}), 200

# ============================================================
# 9. API ẨN/XUẤT BẢN BÀI TẬP
# ============================================================
@chapters_bp.route("/exercises/<int:eid>/toggle-publish", methods=["POST"])
@role_required("teacher")
def toggle_publish_exercise(eid):
    ex = Exercise.query.get(eid)
    if not ex or ex.chapter.teacher_id != int(get_jwt_identity()): return _json_error("Không có quyền.", 403)
    ex.is_published = not ex.is_published
    db.session.commit()
    return jsonify({"success": True, "is_published": ex.is_published}), 200