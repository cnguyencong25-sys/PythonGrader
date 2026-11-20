import secrets
import hashlib
import json
from extensions import db, bcrypt
from sample_cases import sample_examples_from_values
from time_utils import (
    VIETNAM_TZ,
    utc_iso,
    utc_now_naive,
    vietnam_iso,
    vietnam_now_naive,
)

VN_TZ = VIETNAM_TZ


def _normalized_total_score(submissions, question_count):
    if not question_count:
        return 0.0
    score_per_question = 10.0 / question_count
    total = sum(
        (submission.score / submission.max_score) * score_per_question
        for submission in submissions
        if submission.max_score > 0
    )
    return round(min(total, 10.0), 2)


# ============================================================
# 1. NGƯỜI DÙNG
# ============================================================
class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)
    full_name = db.Column(db.String(120), nullable=True)
    class_name = db.Column(db.String(50), nullable=True)
    student_id = db.Column(db.String(50), nullable=True)
    profile_completed = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=utc_now_naive)

    def set_password(self, raw_password: str) -> None:
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode("utf-8")

    def check_password(self, raw_password: str) -> bool:
        return bcrypt.check_password_hash(self.password_hash, raw_password)

    def to_dict(self) -> dict:
        return {
            "id": self.id, "email": self.email, "role": self.role,
            "full_name": self.full_name, "class_name": self.class_name,
            "student_id": self.student_id, "profile_completed": self.profile_completed,
        }


class Announcement(db.Model):
    __tablename__ = "announcements"
    __table_args__ = {"sqlite_autoincrement": True}

    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive, index=True)

    def to_dict(self):
        return {
            "id": self.id,
            "content": self.content,
            "created_at": utc_iso(self.created_at),
        }


class AnnouncementReadState(db.Model):
    __tablename__ = "announcement_read_states"

    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    last_read_announcement_id = db.Column(db.Integer, nullable=False, default=0)


class SystemSetting(db.Model):
    __tablename__ = "system_settings"

    key = db.Column(db.String(80), primary_key=True)
    value = db.Column(db.String(20), nullable=False, default="false")
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive)


# ============================================================
# 2. LOG & PHIÊN ĐĂNG NHẬP
# ============================================================
class LoginLog(db.Model):
    __tablename__ = "login_logs"
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    success = db.Column(db.Boolean, nullable=False, default=False)
    reason = db.Column(db.String(100), nullable=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive, index=True)
    user = db.relationship("User", foreign_keys=[user_id])


class UserSession(db.Model):
    __tablename__ = "user_sessions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(64), unique=True, nullable=False, index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    ip_address = db.Column(db.String(64), nullable=True)
    user_agent = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)
    last_activity = db.Column(db.DateTime, default=utc_now_naive, index=True)
    is_revoked = db.Column(db.Boolean, nullable=False, default=False, index=True)
    revoked_at = db.Column(db.DateTime, nullable=True)
    revoked_reason = db.Column(db.String(50), nullable=True)
    user = db.relationship("User", foreign_keys=[user_id])

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "ip_address": self.ip_address,
            "user_agent": self.user_agent, "created_at": utc_iso(self.created_at),
            "last_activity": utc_iso(self.last_activity),
            "is_revoked": self.is_revoked, "revoked_reason": self.revoked_reason,
        }


# ============================================================
# 3. LỚP HỌC - CHƯƠNG - BÀI TẬP (LUYỆN TẬP)
# ============================================================
class Chapter(db.Model):
    __tablename__ = "chapters"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default="practice")
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)
    is_hidden = db.Column(db.Boolean, nullable=False, default=False)

    teacher = db.relationship("User", foreign_keys=[teacher_id])
    exercises = db.relationship("Exercise", backref="chapter", cascade="all, delete-orphan", order_by="Exercise.created_at")

    def to_dict(self, include_exercises=False, exercises_brief=False):
        data = {
            "id": self.id, "name": self.name, "mode": self.mode, "teacher_id": self.teacher_id,
            "exercise_count": len(self.exercises), "created_at": utc_iso(self.created_at),
            "is_hidden": self.is_hidden,
        }
        if include_exercises:
            if exercises_brief:
                data["exercises"] = [{"id": e.id, "title": e.title, "is_published": e.is_published} for e in self.exercises]
            else:
                data["exercises"] = [e.to_dict() for e in self.exercises]
        return data

class Exercise(db.Model):
    __tablename__ = "exercises"
    id = db.Column(db.Integer, primary_key=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    
    input_format = db.Column(db.Text, nullable=True, default="")
    output_format = db.Column(db.Text, nullable=True, default="")
    constraints = db.Column(db.Text, nullable=True, default="")
    sample_input = db.Column(db.Text, nullable=False, default="")
    sample_output = db.Column(db.Text, nullable=False, default="")
    generator_code = db.Column(db.Text, nullable=True, default="")
    solution_code = db.Column(db.Text, nullable=True, default="")
    num_test_cases = db.Column(db.Integer, nullable=False, default=10)
    
    is_published = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)

    @property
    def sample_examples(self):
        return sample_examples_from_values(self.sample_input, self.sample_output)

    def to_dict(self):
        examples = self.sample_examples
        return {
            "id": self.id, "chapter_id": self.chapter_id, "title": self.title, "description": self.description,
            "input_format": self.input_format, "output_format": self.output_format, "constraints": self.constraints,
            "sample_input": examples[0]["input"] if examples else "",
            "sample_output": examples[0]["output"] if examples else "",
            "sample_examples": examples,
            "generator_code": self.generator_code, "solution_code": self.solution_code,
            "num_test_cases": self.num_test_cases, "is_published": self.is_published,
        }

    def to_student_dict(self):
        examples = self.sample_examples
        return {
            "id": self.id,
            "chapter_id": self.chapter_id,
            "title": self.title,
            "description": self.description,
            "input_format": self.input_format,
            "output_format": self.output_format,
            "constraints": self.constraints,
            "sample_input": examples[0]["input"] if examples else "",
            "sample_output": examples[0]["output"] if examples else "",
            "sample_examples": examples,
        }


# ============================================================
# 4. BÀI KIỂM TRA
# ============================================================
class Exam(db.Model):
    __tablename__ = "exams"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.DateTime(timezone=True), nullable=True)
    end_time = db.Column(db.DateTime(timezone=True), nullable=True)
    duration_minutes = db.Column(db.Integer, nullable=False, default=45)
    max_attempts = db.Column(db.Integer, nullable=False, default=1)
    anti_cheat_enabled = db.Column(
        db.Boolean, nullable=False, default=True, server_default="TRUE"
    )
    password_hash = db.Column(db.String(255), nullable=True)
    access_code = db.Column(db.String(32), unique=True, nullable=False, default=lambda: secrets.token_urlsafe(12))
    teacher_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)

    teacher = db.relationship("User", foreign_keys=[teacher_id])
    exercises = db.relationship("ExamExercise", backref="exam", cascade="all, delete-orphan", order_by="ExamExercise.created_at")

    def to_dict(self, include_exercises=False, exercises_brief=False):
        data = {
            "id": self.id, "name": self.name,
            "start_time": vietnam_iso(self.start_time),
            "end_time": vietnam_iso(self.end_time),
            "duration_minutes": self.duration_minutes, "teacher_id": self.teacher_id,
            "max_attempts": self.max_attempts,
            "anti_cheat_enabled": self.anti_cheat_enabled,
            "access_code": self.access_code,
            "exercise_count": len(self.exercises), "created_at": utc_iso(self.created_at),
        }
        if include_exercises:
            if exercises_brief:
                data["exercises"] = [{"id": e.id, "title": e.title, "is_published": e.is_published} for e in self.exercises]
            else:
                data["exercises"] = [e.to_dict() for e in self.exercises]
        return data

    def set_exam_password(self, raw_password):
        self.password_hash = bcrypt.generate_password_hash(raw_password).decode("utf-8") if raw_password else None

    def check_exam_password(self, raw_password):
        return bool(self.password_hash and raw_password and bcrypt.check_password_hash(self.password_hash, raw_password))


class ExamChapterRule(db.Model):
    __tablename__ = "exam_chapter_rules"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id", ondelete="CASCADE"), nullable=False, index=True)
    question_count = db.Column(db.Integer, nullable=False)
    exam = db.relationship("Exam", backref=db.backref("chapter_rules", cascade="all, delete-orphan"))
    chapter = db.relationship("Chapter")


class PublicExamSession(db.Model):
    __tablename__ = "public_exam_sessions"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    student_id = db.Column(db.String(50), nullable=False, index=True)
    full_name = db.Column(db.String(120), nullable=False)
    class_name = db.Column(db.String(50), nullable=False)
    session_token_hash = db.Column(db.String(64), nullable=False, unique=True)
    attempt_number = db.Column(db.Integer, nullable=False)
    question_ids = db.Column(db.Text, nullable=False, default="[]")
    started_at = db.Column(db.DateTime, nullable=False, default=vietnam_now_naive)
    finished_at = db.Column(db.DateTime, nullable=True)
    is_finalized = db.Column(db.Boolean, nullable=False, default=False)
    violation_count = db.Column(db.Integer, nullable=False, default=0)
    exam = db.relationship("Exam", backref=db.backref("public_sessions", cascade="all, delete-orphan"))
    submissions = db.relationship("PublicExamSubmission", backref="session", cascade="all, delete-orphan")

    def to_dict(self):
        question_count = len(json.loads(self.question_ids or "[]"))
        return {
            "id": self.id,
            "started_at": vietnam_iso(self.started_at),
            "finished_at": vietnam_iso(self.finished_at),
            "is_finalized": self.is_finalized,
            "violation_count": self.violation_count,
            "total_score": _normalized_total_score(self.submissions, question_count),
            "total_max": 10.0 if question_count else 0.0,
        }

    def verify_token(self, token):
        return bool(token and secrets.compare_digest(
            self.session_token_hash, hashlib.sha256(token.encode("utf-8")).hexdigest()
        ))


class PublicExamSubmission(db.Model):
    __tablename__ = "public_exam_submissions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("public_exam_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    question_key = db.Column(db.String(64), nullable=False)
    code = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")
    score = db.Column(db.Float, nullable=False, default=0.0)
    max_score = db.Column(db.Float, nullable=False, default=10.0)
    updated_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive, onupdate=utc_now_naive)

    __table_args__ = (db.UniqueConstraint("session_id", "question_key", name="uq_public_submission_question"),)

    def to_dict(self):
        return {
            "question_key": self.question_key, "code": self.code,
            "status": self.status, "score": self.score, "max_score": self.max_score,
        }

class ExamExercise(db.Model):
    __tablename__ = "exam_exercises"
    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False, default="")
    
    input_format = db.Column(db.Text, nullable=True, default="")
    output_format = db.Column(db.Text, nullable=True, default="")
    constraints = db.Column(db.Text, nullable=True, default="")
    sample_input = db.Column(db.Text, nullable=False, default="")
    sample_output = db.Column(db.Text, nullable=False, default="")
    generator_code = db.Column(db.Text, nullable=True, default="")
    solution_code = db.Column(db.Text, nullable=True, default="")
    num_test_cases = db.Column(db.Integer, nullable=False, default=10)

    is_published = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, default=utc_now_naive)

    @property
    def sample_examples(self):
        return sample_examples_from_values(self.sample_input, self.sample_output)

    def to_dict(self):
        examples = self.sample_examples
        return {
            "id": self.id, "exam_id": self.exam_id, "title": self.title, "description": self.description,
            "input_format": self.input_format, "output_format": self.output_format, "constraints": self.constraints,
            "sample_input": examples[0]["input"] if examples else "",
            "sample_output": examples[0]["output"] if examples else "",
            "sample_examples": examples,
            "generator_code": self.generator_code, "solution_code": self.solution_code,
            "num_test_cases": self.num_test_cases, "is_published": self.is_published,
        }


# ============================================================
# 5. LỊCH SỬ & BÀI NỘP CỦA SINH VIÊN
# ============================================================
class FreePracticeSession(db.Model):
    __tablename__ = "free_practice_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    mode = db.Column(db.String(20), nullable=False)
    chapter_ids = db.Column(db.Text, nullable=False, default="[]")
    question_ids = db.Column(db.Text, nullable=False, default="[]")
    duration_minutes = db.Column(db.Float, nullable=True)
    started_at = db.Column(db.DateTime, nullable=False, default=vietnam_now_naive)
    finished_at = db.Column(db.DateTime, nullable=True)
    is_finalized = db.Column(db.Boolean, nullable=False, default=False)

    user = db.relationship("User", foreign_keys=[user_id])
    submissions = db.relationship(
        "FreePracticeSubmission",
        backref="session",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        try:
            question_count = len(json.loads(self.question_ids or "[]"))
        except (TypeError, ValueError):
            question_count = 0
        total_score = _normalized_total_score(self.submissions, question_count)
        return {
            "id": self.id,
            "mode": self.mode,
            "started_at": vietnam_iso(self.started_at),
            "finished_at": vietnam_iso(self.finished_at),
            "is_finalized": self.is_finalized,
            "total_score": total_score,
            "total_max": 10.0 if question_count else 0.0,
        }


class FreePracticeSubmission(db.Model):
    __tablename__ = "free_practice_submissions"
    __table_args__ = (
        db.UniqueConstraint("session_id", "exercise_id", name="uq_free_session_exercise"),
    )

    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("free_practice_sessions.id"),
        nullable=False,
        index=True,
    )
    exercise_id = db.Column(
        db.Integer,
        db.ForeignKey("exercises.id"),
        nullable=False,
        index=True,
    )
    code = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")
    score = db.Column(db.Float, nullable=False, default=0.0)
    max_score = db.Column(db.Float, nullable=False, default=10.0)
    updated_at = db.Column(db.DateTime, default=utc_now_naive, onupdate=utc_now_naive)

    exercise = db.relationship("Exercise", foreign_keys=[exercise_id])

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "exercise_id": self.exercise_id,
            "code": self.code,
            "status": self.status,
            "score": self.score,
            "max_score": self.max_score,
        }


class ChapterSession(db.Model):
    __tablename__ = "chapter_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    chapter_id = db.Column(db.Integer, db.ForeignKey("chapters.id"), nullable=False, index=True)
    started_at = db.Column(db.DateTime, default=utc_now_naive)
    finished_at = db.Column(db.DateTime, nullable=True)
    is_finalized = db.Column(db.Boolean, default=False)

    user = db.relationship("User", foreign_keys=[user_id])
    chapter = db.relationship("Chapter", foreign_keys=[chapter_id])
    submissions = db.relationship("ChapterSubmission", backref="session", cascade="all, delete-orphan")

    def to_dict(self):
        chapter_exercises = self.chapter.exercises if self.chapter else []
        question_count = sum(1 for exercise in chapter_exercises if exercise.is_published)
        total_score = _normalized_total_score(self.submissions, question_count)
        total_max = 10.0 if question_count else 0.0
        return {
            "id": self.id, "started_at": utc_iso(self.started_at),
            "finished_at": utc_iso(self.finished_at),
            "is_finalized": self.is_finalized, "total_score": total_score, "total_max": total_max,
            "completed_count": len([s for s in self.submissions if s.status == 'correct'])
        }

class ChapterSubmission(db.Model):
    __tablename__ = "chapter_submissions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("chapter_sessions.id"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id"), nullable=False, index=True)
    code = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending") # pending, correct, partial, wrong
    score = db.Column(db.Float, nullable=False, default=0.0)
    max_score = db.Column(db.Float, nullable=False, default=10.0)
    updated_at = db.Column(db.DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    exercise = db.relationship("Exercise", foreign_keys=[exercise_id])

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "exercise_id": self.exercise_id,
            "code": self.code, "status": self.status, "score": self.score, "max_score": self.max_score,
        }

class ExamSession(db.Model):
    __tablename__ = "exam_sessions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False, index=True)
    question_ids = db.Column(db.Text, nullable=False, default="[]")
    started_at = db.Column(db.DateTime, default=vietnam_now_naive)
    finished_at = db.Column(db.DateTime, nullable=True)
    is_finalized = db.Column(db.Boolean, default=False)
    
    user = db.relationship("User", foreign_keys=[user_id])
    exam = db.relationship("Exam", foreign_keys=[exam_id])
    submissions = db.relationship("ExamSubmission", backref="session", cascade="all, delete-orphan")
    chapter_submissions = db.relationship(
        "ExamChapterSubmission", backref="session", cascade="all, delete-orphan"
    )

    def to_dict(self):
        submissions = [*self.submissions, *self.chapter_submissions]
        try:
            question_count = len(json.loads(self.question_ids or "[]"))
        except (TypeError, ValueError):
            question_count = 0
        if not question_count:
            question_count = sum(
                1 for exercise in (self.exam.exercises if self.exam else [])
                if exercise.is_published
            )
        total_score = _normalized_total_score(submissions, question_count)
        total_max = 10.0 if question_count else 0.0
        return {
            "id": self.id, "started_at": vietnam_iso(self.started_at),
            "finished_at": vietnam_iso(self.finished_at),
            "is_finalized": self.is_finalized, "total_score": total_score, "total_max": total_max,
        }


class ExamMonitoringRecord(db.Model):
    __tablename__ = "exam_monitoring_records"
    __table_args__ = (
        db.UniqueConstraint("exam_id", "user_id", name="uq_exam_monitoring_user"),
    )

    id = db.Column(db.Integer, primary_key=True)
    exam_id = db.Column(
        db.Integer, db.ForeignKey("exams.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_session_id = db.Column(
        db.Integer, db.ForeignKey("exam_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    device_id = db.Column(db.String(64), nullable=True)
    abnormal_count = db.Column(db.Integer, nullable=False, default=0)
    is_blocked = db.Column(db.Boolean, nullable=False, default=False)
    is_cheating = db.Column(db.Boolean, nullable=False, default=False)
    blocked_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=vietnam_now_naive, onupdate=vietnam_now_naive)

    exam = db.relationship("Exam", backref=db.backref("monitoring_records", cascade="all, delete-orphan"))
    user = db.relationship("User", foreign_keys=[user_id])
    current_session = db.relationship("ExamSession", foreign_keys=[current_session_id])
    events = db.relationship(
        "ExamProctoringEvent",
        back_populates="record",
        cascade="all, delete-orphan",
        order_by="ExamProctoringEvent.occurred_at",
    )


class ExamProctoringEvent(db.Model):
    __tablename__ = "exam_proctoring_events"
    __table_args__ = (
        db.Index(
            "uq_exam_proctoring_event_token",
            "record_id",
            "session_id",
            "event_token",
            unique=True,
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    record_id = db.Column(
        db.Integer,
        db.ForeignKey("exam_monitoring_records.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_id = db.Column(
        db.Integer,
        db.ForeignKey("exam_sessions.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type = db.Column(db.String(32), nullable=False, index=True)
    detail = db.Column(db.String(255), nullable=False, default="")
    event_token = db.Column(db.String(32), nullable=True)
    occurred_at = db.Column(db.DateTime, nullable=False, default=vietnam_now_naive, index=True)

    record = db.relationship("ExamMonitoringRecord", back_populates="events")


class ExamRetakePermission(db.Model):
    __tablename__ = "exam_retake_permissions"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    exam_id = db.Column(db.Integer, db.ForeignKey("exams.id"), nullable=False, index=True)
    granted_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    granted_at = db.Column(db.DateTime, nullable=False, default=utc_now_naive)
    used_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        db.UniqueConstraint("user_id", "exam_id", name="uq_exam_retake_user_exam"),
    )


class ExamSubmission(db.Model):
    __tablename__ = "exam_submissions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("exam_sessions.id"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exam_exercises.id"), nullable=False, index=True)
    code = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")
    score = db.Column(db.Float, nullable=False, default=0.0)
    max_score = db.Column(db.Float, nullable=False, default=10.0)
    updated_at = db.Column(db.DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    exercise = db.relationship("ExamExercise", foreign_keys=[exercise_id])

    def to_dict(self):
        return {
            "id": self.id, "session_id": self.session_id, "exercise_id": self.exercise_id,
            "code": self.code, "status": self.status, "score": self.score, "max_score": self.max_score,
        }


class ExamChapterSubmission(db.Model):
    __tablename__ = "exam_chapter_submissions"
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey("exam_sessions.id"), nullable=False, index=True)
    exercise_id = db.Column(db.Integer, db.ForeignKey("exercises.id"), nullable=False, index=True)
    code = db.Column(db.Text, nullable=False, default="")
    status = db.Column(db.String(20), nullable=False, default="pending")
    score = db.Column(db.Float, nullable=False, default=0.0)
    max_score = db.Column(db.Float, nullable=False, default=10.0)
    updated_at = db.Column(db.DateTime, default=utc_now_naive, onupdate=utc_now_naive)
    exercise = db.relationship("Exercise", foreign_keys=[exercise_id])

    __table_args__ = (
        db.UniqueConstraint("session_id", "exercise_id", name="uq_exam_chapter_submission"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "session_id": self.session_id,
            "exercise_id": f"chapter-{self.exercise_id}",
            "code": self.code,
            "status": self.status,
            "score": self.score,
            "max_score": self.max_score,
        }