import unittest
from datetime import datetime, timedelta, timezone

from flask_jwt_extended import create_access_token

from app import _upgrade_existing_schema, create_app
from extensions import db
from models import (
    Chapter,
    ChapterSession,
    ChapterSubmission,
    Exam,
    ExamExercise,
    ExamRetakePermission,
    ExamSession,
    ExamSubmission,
    Exercise,
    LoginLog,
    User,
    UserSession,
    VN_TZ,
)


class TeacherStudentManagementTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            self.teacher = User(email="teacher@example.invalid", role="teacher")
            self.teacher.set_password("test-password")
            self.student = User(
                email="student@example.invalid",
                role="student",
                full_name="Sinh viên kiểm thử",
                student_id="SV001",
                class_name="CTK44",
                profile_completed=True,
            )
            self.student.set_password("test-password")
            db.session.add_all([self.teacher, self.student])
            db.session.flush()
            self.exam = Exam(
                name="Bài thi của giáo viên",
                teacher_id=self.teacher.id,
                start_time=datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(minutes=1),
                duration_minutes=30,
                max_attempts=1,
            )
            self.exam.set_exam_password("exam-pass")
            db.session.add(self.exam)
            db.session.flush()
            db.session.add(ExamExercise(
                exam_id=self.exam.id,
                title="Câu 1",
                description="Câu hỏi",
            ))
            db.session.commit()
            self.teacher_id = self.teacher.id
            self.student_id = self.student.id
            self.exam_id = self.exam.id
            self.exam_exercise_id = ExamExercise.query.filter_by(
                exam_id=self.exam.id
            ).one().id
            self.student_email = self.student.email
        self.authenticate(self.teacher_id, "teacher")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def authenticate(self, user_id, role):
        with self.app.app_context():
            token = create_access_token(
                identity=str(user_id), additional_claims={"role": role}
            )
        self.client.set_cookie("access_token_cookie", token)

    def test_list_history_scope_attempt_order_and_retake_flow(self):
        with self.app.app_context():
            additional_student = User(
                email="another-student@example.invalid",
                role="student",
                full_name="Sinh viên bổ sung",
            )
            additional_student.set_password("test-password")
            db.session.add(additional_student)
            db.session.flush()
            additional_student_id = additional_student.id
            other_teacher = User(email="other-teacher@example.invalid", role="teacher")
            other_teacher.set_password("test-password")
            db.session.add(other_teacher)
            db.session.flush()
            other_exam = Exam(name="Bài thi khác", teacher_id=other_teacher.id)
            db.session.add(other_exam)
            db.session.flush()
            now = datetime.now(VN_TZ).replace(tzinfo=None)
            for offset, code, is_finalized in (
                (20, "print('old')", True),
                (10, "print('latest')", False),
            ):
                session = ExamSession(
                    user_id=self.student_id,
                    exam_id=self.exam_id,
                    started_at=now - timedelta(minutes=offset),
                    finished_at=(
                        now - timedelta(minutes=offset - 1) if is_finalized else None
                    ),
                    is_finalized=is_finalized,
                )
                db.session.add(session)
                db.session.flush()
                db.session.add(ExamSubmission(
                    session_id=session.id,
                    exercise_id=self._exam_exercise_id(),
                    code=code,
                    status="correct",
                    score=10,
                    max_score=10,
                ))
            db.session.add(ExamSession(
                user_id=self.student_id,
                exam_id=other_exam.id,
                is_finalized=True,
            ))
            db.session.commit()

        listing = self.client.get("/api/teacher/students")
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(
            {item["id"] for item in listing.json["students"]},
            {self.student_id, additional_student_id},
        )

        history_page = self.client.get(
            f"/teacher/students/{self.student_id}/history"
        )
        self.assertEqual(history_page.status_code, 200)
        history = self.client.get(
            f"/api/teacher/students/{self.student_id}/exam-history"
        )
        self.assertEqual(history.status_code, 200)
        attempts = history.json["attempts"]
        self.assertEqual([attempt["attempt_number"] for attempt in attempts], [2, 1])
        self.assertEqual(attempts[1]["time_taken_seconds"], 60)
        self.assertTrue(attempts[1]["started_at"].endswith("+07:00"))
        self.assertTrue(attempts[1]["finished_at"].endswith("+07:00"))
        self.assertEqual([attempt["exam_name"] for attempt in attempts], [
            "Bài thi của giáo viên", "Bài thi của giáo viên",
        ])
        self.assertEqual(attempts[0]["submissions"][0]["code"], "print('latest')")
        score_rows = self.client.get(f"/api/exams/{self.exam_id}/scores")
        self.assertEqual(score_rows.status_code, 200)
        student_score = next(
            row for row in score_rows.json["scores"]
            if row["student_id"] == "SV001"
        )
        self.assertEqual(student_score["time_taken"], "0:01:00")
        self.assertTrue(student_score["started_at"].endswith("+07:00"))

        granted = self.client.post(
            f"/api/teacher/students/{self.student_id}/exams/{self.exam_id}/allow-retake"
        )
        self.assertEqual(granted.status_code, 200)
        with self.app.app_context():
            stored_sessions = ExamSession.query.filter_by(
                user_id=self.student_id, exam_id=self.exam_id
            ).all()
            self.assertTrue(all(session.is_finalized for session in stored_sessions))
            self.assertTrue(all(session.finished_at for session in stored_sessions))

        self.authenticate(self.student_id, "student")
        started = self.client.post(
            f"/api/student/exams/{self.exam_id}/start",
            json={"password": "exam-pass"},
        )
        self.assertEqual(started.status_code, 201)
        self.assertFalse(started.json["is_resumed"])
        with self.app.app_context():
            permission = ExamRetakePermission.query.filter_by(
                user_id=self.student_id, exam_id=self.exam_id
            ).one()
            self.assertIsNotNone(permission.used_at)
            self.assertEqual(
                ExamSession.query.filter_by(
                    user_id=self.student_id, exam_id=self.exam_id
                ).count(),
                3,
            )

    def test_legacy_utc_finish_time_is_migrated_once(self):
        with self.app.app_context():
            started_at = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(minutes=10)
            legacy_finished_at = datetime.now(timezone.utc).replace(tzinfo=None)
            session = ExamSession(
                user_id=self.student_id,
                exam_id=self.exam_id,
                started_at=started_at,
                finished_at=legacy_finished_at,
                is_finalized=True,
            )
            db.session.add(session)
            db.session.commit()

            _upgrade_existing_schema()
            db.session.refresh(session)
            migrated_finished_at = session.finished_at
            self.assertEqual(
                migrated_finished_at, legacy_finished_at + timedelta(hours=7)
            )

            _upgrade_existing_schema()
            db.session.refresh(session)
            self.assertEqual(session.finished_at, migrated_finished_at)

    def _exam_exercise_id(self):
        return self.exam_exercise_id

    def test_delete_removes_student_account_and_linked_data(self):
        with self.app.app_context():
            chapter = Chapter(name="Chương kiểm thử", teacher_id=self.teacher_id)
            db.session.add(chapter)
            db.session.flush()
            exercise = Exercise(
                chapter_id=chapter.id,
                title="Bài luyện tập",
                description="Mô tả",
            )
            exam_exercise = db.session.get(ExamExercise, self.exam_exercise_id)
            db.session.add(exercise)
            db.session.flush()
            chapter_session = ChapterSession(
                user_id=self.student_id,
                chapter_id=chapter.id,
            )
            exam_session = ExamSession(
                user_id=self.student_id,
                exam_id=self.exam_id,
            )
            db.session.add_all([chapter_session, exam_session])
            db.session.flush()
            db.session.add_all([
                ChapterSubmission(
                    session_id=chapter_session.id,
                    exercise_id=exercise.id,
                    code="print('practice')",
                ),
                ExamSubmission(
                    session_id=exam_session.id,
                    exercise_id=exam_exercise.id,
                    code="print('exam')",
                ),
                ExamRetakePermission(
                    user_id=self.student_id,
                    exam_id=self.exam_id,
                    granted_by=self.teacher_id,
                ),
                LoginLog(
                    email=self.student_email,
                    user_id=self.student_id,
                    success=True,
                ),
                UserSession(
                    session_id="student-session-test",
                    user_id=self.student_id,
                ),
            ])
            db.session.commit()

        response = self.client.delete(f"/api/teacher/students/{self.student_id}")
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertIsNone(db.session.get(User, self.student_id))
            self.assertEqual(ChapterSession.query.filter_by(user_id=self.student_id).count(), 0)
            self.assertEqual(ChapterSubmission.query.count(), 0)
            self.assertEqual(ExamSession.query.filter_by(user_id=self.student_id).count(), 0)
            self.assertEqual(ExamSubmission.query.count(), 0)
            self.assertEqual(ExamRetakePermission.query.filter_by(user_id=self.student_id).count(), 0)
            self.assertEqual(LoginLog.query.filter_by(user_id=self.student_id).count(), 0)
            self.assertEqual(UserSession.query.filter_by(user_id=self.student_id).count(), 0)


if __name__ == "__main__":
    unittest.main()
