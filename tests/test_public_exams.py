import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import inspect, text
from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import Chapter, Exam, ExamChapterRule, ExamExercise, ExamSession, Exercise, VN_TZ, User


class PublicExamFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            teacher = User(email="teacher-test@example.invalid", role="teacher")
            teacher.set_password("test-password")
            db.session.add(teacher)
            db.session.flush()
            self.exam = Exam(
                name="Kiểm tra thử", teacher_id=teacher.id,
                start_time=datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(minutes=1),
                duration_minutes=30, max_attempts=1,
            )
            self.exam.set_exam_password("exam-pass")
            db.session.add(self.exam)
            db.session.flush()
            exam_exercise = ExamExercise(
                exam_id=self.exam.id, title="Câu 1", description="In số 1",
                generator_code="print(1)", solution_code="print(1)",
                num_test_cases=1, is_published=True,
            )
            db.session.add(exam_exercise)
            db.session.commit()
            self.access_code = self.exam.access_code

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def start_exam(self, password="exam-pass"):
        return self.client.post(
            f"/api/public-exams/{self.access_code}/start",
            json={
                "full_name": "Sinh viên A", "student_id": "SV001",
                "class_name": "CTK44", "password": password,
            },
        )

    def test_password_is_required_and_session_can_be_resumed_and_reviewed(self):
        response = self.client.get(f"/api/public-exams/{self.access_code}")
        self.assertTrue(response.json["password_configured"])
        self.assertTrue(response.json["start_time"].endswith("+07:00"))
        self.assertNotIn("password_hash", response.json)
        self.assertEqual(self.start_exam("wrong").status_code, 403)

        started = self.start_exam()
        self.assertEqual(started.status_code, 201)
        session_id = started.json["session_id"]
        token = started.json["session_token"]
        headers = {"X-Exam-Session-Token": token}
        draft = self.client.post(
            f"/api/public-exams/sessions/{session_id}/save-draft",
            json={"question_id": "exam-1", "code": "print(1)"},
            headers=headers,
        )
        self.assertEqual(draft.status_code, 200)

        resumed = self.start_exam()
        self.assertTrue(resumed.json["is_resumed"])
        token = resumed.json["session_token"]
        headers = {"X-Exam-Session-Token": token}
        violations = self.client.post(
            f"/api/public-exams/sessions/{session_id}/violation", headers=headers,
        )
        self.assertEqual(violations.json["violation_count"], 1)

        finished = self.client.post(
            f"/api/public-exams/sessions/{session_id}/finish", headers=headers,
        )
        self.assertEqual(finished.json["result"]["total_score"], 10.0)
        self.assertTrue(finished.json["result"]["started_at"].endswith("+07:00"))
        self.assertTrue(finished.json["result"]["finished_at"].endswith("+07:00"))
        review = self.start_exam()
        self.assertTrue(review.json["read_only"])
        self.assertEqual(review.json["session_id"], session_id)
        readonly_data = self.client.get(
            f"/api/public-exams/sessions/{session_id}",
            headers={"X-Exam-Session-Token": review.json["session_token"]},
        )
        self.assertTrue(readonly_data.json["read_only"])
        self.assertEqual(readonly_data.json["submissions"]["exam-1"]["code"], "print(1)")

    def test_exam_link_cannot_be_used_before_start_time_or_without_password(self):
        with self.app.app_context():
            exam = Exam.query.filter_by(access_code=self.access_code).first()
            exam.start_time = datetime.now(VN_TZ).replace(tzinfo=None) + timedelta(hours=1)
            db.session.commit()
        before_start = self.start_exam()
        self.assertEqual(before_start.status_code, 403)

        with self.app.app_context():
            exam = Exam.query.filter_by(access_code=self.access_code).first()
            exam.start_time = datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(minutes=1)
            exam.set_exam_password("")
            db.session.commit()
        no_password = self.start_exam()
        self.assertEqual(no_password.status_code, 403)

    def test_chapter_rules_select_random_questions_without_exposing_solutions(self):
        with self.app.app_context():
            exam = Exam.query.filter_by(access_code=self.access_code).first()
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            chapter = Chapter(name="Chương ngẫu nhiên", teacher_id=teacher.id)
            db.session.add(chapter)
            db.session.flush()
            db.session.add_all([
                Exercise(
                    chapter_id=chapter.id, title=f"Câu {number}", description="Đề bài",
                    generator_code="print(1)", solution_code="print(1)", is_published=True,
                )
                for number in range(2)
            ])
            db.session.flush()
            db.session.add(ExamChapterRule(exam_id=exam.id, chapter_id=chapter.id, question_count=1))
            db.session.commit()

        started = self.start_exam()
        token = started.json["session_token"]
        response = self.client.get(
            f"/api/public-exams/sessions/{started.json['session_id']}",
            headers={"X-Exam-Session-Token": token},
        )
        questions = response.json["exam"]["exercises"]
        self.assertEqual(len(questions), 1)
        self.assertTrue(questions[0]["id"].startswith("chapter-"))
        self.assertNotIn("solution_code", questions[0])

    def test_public_exam_pages_render_without_student_login(self):
        join_page = self.client.get(f"/exam/{self.access_code}")
        self.assertEqual(join_page.status_code, 200)
        started = self.start_exam()
        workspace_page = self.client.get(
            f"/exam/{self.access_code}/workspace/{started.json['session_id']}"
        )
        self.assertEqual(workspace_page.status_code, 200)
        self.assertIn(b'id="studentThemeToggle"', workspace_page.data)
        self.assertIn(b"/static/js/student_theme.js", workspace_page.data)

    def test_teacher_exam_pages_render_redesigned_forms(self):
        with self.app.app_context():
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            token = create_access_token(
                identity=str(teacher.id), additional_claims={"role": "teacher"}
            )
            exam_id = self.exam.id
        self.client.set_cookie("access_token_cookie", token)

        exam_list = self.client.get("/teacher/exams")
        self.assertEqual(exam_list.status_code, 200)
        self.assertIn(b"exam-modal", exam_list.data)
        exam_edit = self.client.get(f"/teacher/exams/{exam_id}/edit")
        self.assertEqual(exam_edit.status_code, 200)
        self.assertIn(b"exam-settings-grid", exam_edit.data)
        self.assertIn(b"examPassword", exam_edit.data)
        self.assertNotIn(b"studentExamLink", exam_edit.data)

    def test_student_must_enter_exam_password_before_a_session_is_created(self):
        with self.app.app_context():
            student = User(email="student-test@example.invalid", role="student")
            student.set_password("test-password")
            student.profile_completed = True
            db.session.add(student)
            db.session.flush()
            student_id = student.id
            token = create_access_token(
                identity=str(student.id), additional_claims={"role": "student"}
            )
            db.session.commit()
        self.client.set_cookie("access_token_cookie", token)

        student_page = self.client.get("/student/exams")
        self.assertEqual(student_page.status_code, 200)
        self.assertIn(b"examPasswordModal", student_page.data)

        exam_list = self.client.get("/api/student/exams")
        self.assertTrue(exam_list.json["exams"][0]["password_configured"])
        self.assertNotIn("password_hash", exam_list.json["exams"][0])

        wrong_password = self.client.post(
            f"/api/student/exams/{self.exam.id}/start",
            json={"password": "incorrect"},
        )
        self.assertEqual(wrong_password.status_code, 403)
        with self.app.app_context():
            self.assertEqual(
                ExamSession.query.filter_by(user_id=student_id, exam_id=self.exam.id).count(),
                0,
            )

        started = self.client.post(
            f"/api/student/exams/{self.exam.id}/start",
            json={"password": "exam-pass"},
        )
        self.assertEqual(started.status_code, 201)

    def test_existing_exam_table_is_upgraded_and_receives_public_link(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = os.path.join(directory, "legacy.sqlite3")
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE exams (id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, "
                "start_time DATETIME, end_time DATETIME, duration_minutes INTEGER NOT NULL, "
                "teacher_id INTEGER NOT NULL, created_at DATETIME)"
            )
            connection.execute(
                "INSERT INTO exams (id, name, duration_minutes, teacher_id) VALUES (10, 'Legacy', 30, 1)"
            )
            connection.commit()
            connection.close()

            migrated_app = create_app({
                "TESTING": True,
                "SQLALCHEMY_DATABASE_URI": f"sqlite:///{database_path}",
                "SECRET_KEY": "test-secret",
                "JWT_SECRET_KEY": "test-jwt-secret",
            })
            with migrated_app.app_context():
                engine = db.engine
                columns = {column["name"] for column in inspect(engine).get_columns("exams")}
                row = db.session.execute(
                    text("SELECT max_attempts, password_hash, access_code FROM exams WHERE id = 10")
                ).one()
                db.session.remove()
                engine.dispose()
            self.assertTrue({"max_attempts", "password_hash", "access_code"}.issubset(columns))
            self.assertEqual(row.max_attempts, 1)
            self.assertIsNone(row.password_hash)
            self.assertTrue(row.access_code)


if __name__ == "__main__":
    unittest.main()
