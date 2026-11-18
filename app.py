import os
import secrets
from datetime import timedelta
from flask import Flask, render_template, jsonify, redirect, request
from sqlalchemy import inspect, text
from flask_jwt_extended import jwt_required, get_jwt, get_jwt_identity
from config import Config
from extensions import db, bcrypt, jwt

# Import toàn bộ Models (bao gồm cả Session của Chương và Bài kiểm tra)
from models import (
    User, Chapter, Exercise, Exam, ExamExercise, 
    ChapterSession, ChapterSubmission, 
    ExamSession, ExamSubmission, PublicExamSession
)

from auth import auth_bp
from chapters import chapters_bp
from exams import exams_bp
from student_api import student_api_bp, public_exam_bp
from teacher_students import teacher_students_bp
from announcements import announcements_bp
from session_manager import (
    verify_session, list_active_sessions, count_active_sessions,
    IDLE_TIMEOUT_MINUTES
)
from time_utils import vietnam_datetime_local_value


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.from_object(Config)
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    bcrypt.init_app(app)
    jwt.init_app(app)
    app.jinja_env.filters["vietnam_datetime_local"] = vietnam_datetime_local_value

    # Đăng ký các Blueprint (API)
    app.register_blueprint(auth_bp)
    app.register_blueprint(chapters_bp)
    app.register_blueprint(exams_bp)
    app.register_blueprint(student_api_bp)
    app.register_blueprint(public_exam_bp)
    app.register_blueprint(teacher_students_bp)
    app.register_blueprint(announcements_bp)

    # ============================================================
    # HOOK: kiểm tra session MỖI REQUEST có auth (Single-session)
    # ============================================================
    @app.before_request
    def _check_session_alive():
        path = request.path

        # Bỏ qua route công khai / static
        skip_prefixes = (
            "/static/",
            "/exam/",
            "/api/public-exams/",
            "/api/auth/login",
            "/api/auth/register",
            "/login",
            "/register",
        )
        if any(path.startswith(p) for p in skip_prefixes):
            return None

        token = request.cookies.get("access_token_cookie")
        if not token:
            return None

        try:
            from flask_jwt_extended import decode_token
            claims = decode_token(token)
        except Exception:
            return None

        sid = claims.get("sid")
        if not sid:
            return None

        ok, reason = verify_session(sid)
        if ok:
            return None

        # Session chết -> đá về login
        if path.startswith("/api/"):
            resp = jsonify({
                "success": False,
                "message": "Phiên đăng nhập đã hết hạn.",
                "reason": reason,
            })
            resp.status_code = 401
            from flask_jwt_extended import unset_jwt_cookies
            unset_jwt_cookies(resp)
            return resp
        else:
            return redirect(f"/login?expired={reason or 'session'}")

    # ============================================================
    # ROUTE TRANG CÔNG KHAI
    # ============================================================
    @app.route("/")
    def index():
        return render_template("login.html")

    @app.route("/login")
    def login_page():
        return render_template("login.html")

    @app.route("/register")
    def register_page():
        return render_template("register.html")

    @app.route("/exam/<access_code>")
    def public_exam_page(access_code):
        exam = Exam.query.filter_by(access_code=access_code).first()
        if not exam:
            return render_template("login.html"), 404
        return render_template("public_exam_join.html", exam=exam)

    @app.route("/exam/<access_code>/workspace/<int:sid>")
    def public_exam_workspace_page(access_code, sid):
        session = PublicExamSession.query.filter_by(id=sid).first()
        if not session or session.exam.access_code != access_code:
            return redirect(f"/exam/{access_code}")
        return render_template("public_exam_workspace.html", exam=session.exam, session_id=sid)

    # ============================================================
    # ROUTE GIÁO VIÊN
    # ============================================================
    @app.route("/teacher/dashboard")
    @jwt_required()
    def teacher_dashboard():
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        return redirect("/teacher/chapters")

    @app.route("/teacher/students")
    @jwt_required()
    def teacher_students_page():
        if get_jwt().get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        if not user:
            return redirect("/login")
        return render_template(
            "teacher_students.html", user=user, active_tab="students"
        )

    @app.route("/teacher/students/<int:student_user_id>/history")
    @jwt_required()
    def teacher_student_history_page(student_user_id):
        if get_jwt().get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        student = User.query.filter_by(
            id=student_user_id, role="student"
        ).first()
        if not user:
            return redirect("/login")
        if not student:
            return redirect("/teacher/students")
        return render_template(
            "teacher_student_history.html",
            user=user,
            student=student,
            active_tab="students",
        )

    # ---------- Quản lý chương ----------
    @app.route("/teacher/chapters")
    @jwt_required()
    def teacher_chapters_page():
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        return render_template("teacher_chapters.html", user=user, active_tab="chapters")

    @app.route("/teacher/chapters/<int:cid>/edit")
    @jwt_required()
    def teacher_chapter_edit_page(cid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        chapter = Chapter.query.filter_by(id=cid, teacher_id=user.id).first()
        if not chapter:
            return redirect("/teacher/chapters")
        return render_template(
            "teacher_chapter_edit.html",
            user=user, chapter=chapter, active_tab="chapters"
        )

    @app.route("/teacher/chapters/<int:cid>/exercises/new")
    @jwt_required()
    def teacher_exercise_new_page(cid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        chapter = Chapter.query.filter_by(id=cid, teacher_id=user.id).first()
        if not chapter:
            return redirect("/teacher/chapters")
        return render_template(
            "teacher_exercise_edit.html",
            user=user, chapter=chapter, exercise=None, active_tab="chapters"
        )

    @app.route("/teacher/chapters/exercises/<int:eid>/edit")
    @jwt_required()
    def teacher_exercise_edit_page(eid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        exercise = Exercise.query.get(eid)
        if not exercise or exercise.chapter.teacher_id != user.id:
            return redirect("/teacher/chapters")
        return render_template(
            "teacher_exercise_edit.html",
            user=user, chapter=exercise.chapter, exercise=exercise,
            active_tab="chapters"
        )

    # ---------- Quản lý bài kiểm tra ----------
    @app.route("/teacher/exams")
    @jwt_required()
    def teacher_exams_page():
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        return render_template("teacher_exams.html", user=user, active_tab="exams")

    @app.route("/teacher/exams/<int:eid>/edit")
    @jwt_required()
    def teacher_exam_edit_page(eid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        exam = Exam.query.filter_by(id=eid, teacher_id=user.id).first()
        if not exam:
            return redirect("/teacher/exams")
        return render_template("teacher_exam_edit.html", user=user, exam=exam, active_tab="exams")

    @app.route("/teacher/exams/<int:eid>/scores")
    @jwt_required()
    def teacher_exam_scores_page(eid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        exam = Exam.query.filter_by(id=eid, teacher_id=user.id).first()
        if not exam:
            return redirect("/teacher/exams")
        return render_template("teacher_exam_scores.html", user=user, exam=exam, active_tab="exams")

    @app.route("/teacher/exams/<int:eid>/exercises/new")
    @jwt_required()
    def teacher_exam_exercise_new_page(eid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        exam = Exam.query.filter_by(id=eid, teacher_id=user.id).first()
        if not exam:
            return redirect("/teacher/exams")
        return render_template(
            "teacher_exam_exercise_edit.html",
            user=user, exam=exam, exercise=None, active_tab="exams"
        )

    @app.route("/teacher/exams/exercises/<int:exid>/edit")
    @jwt_required()
    def teacher_exam_exercise_edit_page(exid):
        claims = get_jwt()
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        exercise = ExamExercise.query.get(exid)
        if not exercise or exercise.exam.teacher_id != user.id:
            return redirect("/teacher/exams")
        return render_template(
            "teacher_exam_exercise_edit.html",
            user=user, exam=exercise.exam, exercise=exercise, active_tab="exams"
        )

    # ============================================================
    # ROUTE SINH VIÊN
    # ============================================================
    @app.route("/student/complete-profile")
    @jwt_required()
    def student_complete_profile_page():
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        if not user:
            return redirect("/login")
        if user.profile_completed:
            return redirect("/student/dashboard")
        return render_template("complete_profile.html", user=user)

    @app.route("/student/profile")
    @jwt_required()
    def student_profile_page():
        if get_jwt().get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        if not user:
            return redirect("/login")
        if not user.profile_completed:
            return redirect("/student/complete-profile")
        return render_template(
            "student_profile.html", user=user, active_tab="profile"
        )

    @app.route("/student/dashboard")
    @jwt_required()
    def student_dashboard():
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        if not user:
            return redirect("/login")
        if not user.profile_completed:
            return redirect("/student/complete-profile")
        return redirect("/student/chapters")

    # --- LUYỆN TẬP CHƯƠNG ---
    @app.route("/student/chapters")
    @jwt_required()
    def student_chapters_page():
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        if not user.profile_completed:
            return redirect("/student/complete-profile")
        return render_template("student_chapters.html", user=user, active_tab="chapters")

    @app.route("/student/chapters/<int:cid>")
    @jwt_required()
    def student_chapter_detail_page(cid):
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        chapter = Chapter.query.get(cid)
        if not chapter:
            return redirect("/student/chapters")
        return render_template("student_chapter_detail.html", user=user, chapter=chapter, active_tab="chapters")

    @app.route("/student/workspace")
    @jwt_required()
    def student_workspace_page():
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        
        sid = request.args.get("session_id", type=int)
        if not sid: return redirect("/student/chapters")
        
        session = ChapterSession.query.filter_by(id=sid, user_id=user.id).first()
        if not session: return redirect("/student/chapters")

        return render_template("student_workspace.html", user=user, chapter=session.chapter, session_id=session.id, active_tab="chapters")

    # --- BÀI KIỂM TRA ---
    @app.route("/student/exams")
    @jwt_required()
    def student_exams_page():
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        if not user.profile_completed:
            return redirect("/student/complete-profile")
        return render_template("student_exams.html", user=user, active_tab="exams")

    @app.route("/student/exam-workspace")
    @jwt_required()
    def student_exam_workspace_page():
        claims = get_jwt()
        if claims.get("role") != "student":
            return redirect("/teacher/dashboard")
        user = User.query.get(int(get_jwt_identity()))
        
        sid = request.args.get("session_id", type=int)
        if not sid: return redirect("/student/exams")
        
        session = ExamSession.query.filter_by(id=sid, user_id=user.id).first()
        if not session: return redirect("/student/exams")

        return render_template("student_exam_workspace.html", user=user, exam=session.exam, session_id=session.id, active_tab="exams")


    # ============================================================
    # TRANG QUẢN LÝ PHIÊN (Dùng chung)
    # ============================================================
    @app.route("/profile")
    @jwt_required()
    def profile_page():
        claims = get_jwt()
        # 🔒 CHỈ GIÁO VIÊN được xem
        if claims.get("role") != "teacher":
            return redirect("/student/dashboard")

        user_id = int(get_jwt_identity())
        user = User.query.get(user_id)
        if not user:
            return redirect("/login")

        current_sid = claims.get("sid")
        sessions = list_active_sessions(user_id, except_session_id=current_sid)

        return render_template(
            "profile.html",
            user=user,
            sessions=sessions,
            current_session_id=current_sid,
            idle_minutes=IDLE_TIMEOUT_MINUTES,
        )

    @app.route("/api/sessions", methods=["GET"])
    @jwt_required()
    def api_list_sessions():
        user_id = int(get_jwt_identity())
        current_sid = get_jwt().get("sid")
        sessions = list_active_sessions(user_id, except_session_id=current_sid)
        return jsonify({
            "success": True,
            "count": len(sessions),
            "sessions": [s.to_dict() for s in sessions],
        }), 200

    # ============================================================
    # KHỞI TẠO DATABASE
    # ============================================================
    with app.app_context():
        db.create_all()
        _upgrade_existing_schema()
        if not app.config.get("TESTING"):
            _seed_teacher()

    return app


def _seed_teacher():
    email = (os.getenv("TEACHER_EMAIL") or "").strip().lower()
    password = os.getenv("TEACHER_PASSWORD") or ""
    fullname = os.getenv("TEACHER_FULLNAME", "Giáo viên")

    if not email or not password:
        print("⚠️  Chưa cấu hình TEACHER_EMAIL / TEACHER_PASSWORD trong .env")
        return

    existing = User.query.filter_by(email=email).first()
    if existing:
        print(f"ℹ️  Tài khoản GV đã tồn tại: {email}")
        return

    teacher = User(email=email, role="teacher",
                   full_name=fullname, profile_completed=True)
    teacher.set_password(password)
    db.session.add(teacher)
    db.session.commit()
    print(f"✅ Đã tạo tài khoản giáo viên: {email}")


def _upgrade_existing_schema():
    columns = {column["name"] for column in inspect(db.engine).get_columns("exams")}
    session_columns = {
        column["name"] for column in inspect(db.engine).get_columns("exam_sessions")
    }
    additions = {
        "max_attempts": "INTEGER NOT NULL DEFAULT 1",
        "password_hash": "VARCHAR(255)",
        "access_code": "VARCHAR(32)",
    }
    with db.engine.begin() as connection:
        for column, definition in additions.items():
            if column not in columns:
                connection.execute(text(f"ALTER TABLE exams ADD COLUMN {column} {definition}"))
        if "question_ids" not in session_columns:
            connection.execute(text(
                "ALTER TABLE exam_sessions ADD COLUMN question_ids TEXT NOT NULL DEFAULT '[]'"
            ))
        result = connection.execute(text("SELECT id FROM exams WHERE access_code IS NULL OR access_code = ''"))
        for row in result:
            connection.execute(
                text("UPDATE exams SET access_code = :code WHERE id = :id"),
                {"code": secrets.token_urlsafe(12), "id": row[0]},
            )
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS ix_exams_access_code ON exams (access_code)"))
        if db.engine.dialect.name == "postgresql":
            connection.execute(text(
                "CREATE TABLE IF NOT EXISTS app_schema_migrations "
                "(version VARCHAR(100) PRIMARY KEY)"
            ))
            migration_version = "2026-11-exam-times-vietnam"
            migration_insert = connection.execute(
                text(
                    "INSERT INTO app_schema_migrations (version) VALUES (:version) "
                    "ON CONFLICT (version) DO NOTHING"
                ),
                {"version": migration_version},
            )
            if migration_insert.rowcount:
                # Earlier naive values were interpreted as UTC by PostgreSQL.
                connection.execute(text(
                    "UPDATE exams SET start_time = start_time - INTERVAL '7 hours' "
                    "WHERE start_time IS NOT NULL"
                ))
                connection.execute(text(
                    "UPDATE exams SET end_time = end_time - INTERVAL '7 hours' "
                    "WHERE end_time IS NOT NULL"
                ))

    # Older authenticated exam sessions could have UTC finish times while starts
    # were stored as Vietnam-local naive datetimes.
    legacy_finished_sessions = ExamSession.query.filter(
        ExamSession.finished_at.isnot(None),
        ExamSession.finished_at < ExamSession.started_at,
    ).all()
    for session in legacy_finished_sessions:
        session.finished_at += timedelta(hours=7)
    if legacy_finished_sessions:
        db.session.commit()


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, host="127.0.0.1", port=5000)