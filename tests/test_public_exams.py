import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta

from sqlalchemy import inspect, text
from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import (
    Chapter,
    ChapterSession,
    Exam,
    ExamChapterRule,
    ExamExercise,
    ExamSession,
    Exercise,
    VN_TZ,
    User,
)


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
                output_format="In số nguyên trên một dòng.",
                constraints="1 <= n <= 100",
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
        question = readonly_data.json["exam"]["exercises"][0]
        self.assertEqual(question["output_format"], "In số nguyên trên một dòng.")
        self.assertEqual(question["constraints"], "1 <= n <= 100")

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
        self.assertIn(b"/static/js/student_code_editor.js", workspace_page.data)
        self.assertIn(b'id="problemOutputFormat"', workspace_page.data)
        self.assertIn(b'id="problemConstraints"', workspace_page.data)

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

    def test_multiple_sample_examples_round_trip_for_chapter_and_exam_questions(self):
        examples = [
            {"input": "2 3", "output": "5"},
            {"input": "10 15", "output": "25"},
        ]
        with self.app.app_context():
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            chapter = Chapter(name="Chương mẫu", teacher_id=teacher.id)
            db.session.add(chapter)
            db.session.commit()
            chapter_id = chapter.id
            exam_id = self.exam.id
            token = create_access_token(
                identity=str(teacher.id),
                additional_claims={"role": "teacher"},
            )
        self.client.set_cookie("access_token_cookie", token)

        chapter_response = self.client.post(
            f"/api/chapters/{chapter_id}/exercises",
            json={
                "title": "Câu chương có nhiều mẫu",
                "description": "Cộng hai số.",
                "sample_examples": examples,
            },
        )
        self.assertEqual(chapter_response.status_code, 201)
        chapter_exercise = chapter_response.json["exercise"]
        self.assertEqual(chapter_exercise["sample_examples"], examples)
        self.assertEqual(chapter_exercise["sample_input"], "2 3")

        chapter_page = self.client.get(
            f"/teacher/chapters/exercises/{chapter_exercise['id']}/edit"
        )
        self.assertEqual(chapter_page.status_code, 200)
        self.assertIn(b'id="addSampleCase"', chapter_page.data)
        self.assertIn(b"/static/js/teacher_sample_cases.js", chapter_page.data)
        self.assertIn(b"2 3", chapter_page.data)
        self.assertIn(b"10 15", chapter_page.data)
        updated_chapter_examples = [examples[1]]
        chapter_update = self.client.put(
            f"/api/chapters/exercises/{chapter_exercise['id']}",
            json={"sample_examples": updated_chapter_examples},
        )
        self.assertEqual(chapter_update.status_code, 200)
        self.assertEqual(
            chapter_update.json["exercise"]["sample_examples"],
            updated_chapter_examples,
        )

        legacy_response = self.client.post(
            f"/api/chapters/{chapter_id}/exercises",
            json={
                "title": "Câu chương mẫu cũ",
                "description": "Mẫu tương thích dữ liệu cũ.",
                "sample_input": "[1, 2]",
                "sample_output": "3",
            },
        )
        self.assertEqual(legacy_response.status_code, 201)
        self.assertEqual(
            legacy_response.json["exercise"]["sample_examples"],
            [{"input": "[1, 2]", "output": "3"}],
        )

        exam_response = self.client.post(
            f"/api/exams/{exam_id}/exercises",
            json={
                "title": "Câu thi có nhiều mẫu",
                "description": "Cộng hai số.",
                "sample_examples": examples,
            },
        )
        self.assertEqual(exam_response.status_code, 201)
        exam_exercise = exam_response.json["exercise"]
        self.assertEqual(exam_exercise["sample_examples"], examples)
        exam_update = self.client.put(
            f"/api/exams/exercises/{exam_exercise['id']}",
            json={"sample_examples": [examples[0]]},
        )
        self.assertEqual(exam_update.status_code, 200)
        self.assertEqual(
            exam_update.json["exercise"]["sample_examples"],
            [examples[0]],
        )

        exam_page = self.client.get(
            f"/teacher/exams/exercises/{exam_exercise['id']}/edit"
        )
        self.assertEqual(exam_page.status_code, 200)
        self.assertIn(b'id="addSampleCase"', exam_page.data)
        self.assertIn(b"/static/js/teacher_sample_cases.js", exam_page.data)
        self.assertIn(b"2 3", exam_page.data)
        self.assertNotIn(b"10 15", exam_page.data)

        public_started = self.start_exam()
        public_session = self.client.get(
            f"/api/public-exams/sessions/{public_started.json['session_id']}",
            headers={"X-Exam-Session-Token": public_started.json["session_token"]},
        )
        returned_question = next(
            question
            for question in public_session.json["exam"]["exercises"]
            if question["title"] == "Câu thi có nhiều mẫu"
        )
        self.assertEqual(returned_question["sample_examples"], [examples[0]])

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
        workspace = self.client.get(
            f"/api/student/exam-sessions/{started.json['session_id']}"
        )
        self.assertEqual(workspace.status_code, 200)
        self.assertTrue(
            workspace.json["exam"]["exercises"][0]["id"].startswith("exam-")
        )
        submission = self.client.post(
            f"/api/student/exam-sessions/{started.json['session_id']}/submit",
            json={
                "exercise_id": workspace.json["exam"]["exercises"][0]["id"],
                "code": "print(1)",
            },
        )
        self.assertEqual(submission.status_code, 200)
        self.assertEqual(submission.json["result"]["status"], "correct")

    def test_authenticated_exam_loads_and_grades_random_chapter_questions(self):
        with self.app.app_context():
            exam = Exam.query.filter_by(access_code=self.access_code).first()
            exam.exercises[0].is_published = False
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            student = User(email="chapter-exam-student@example.invalid", role="student")
            student.set_password("test-password")
            student.profile_completed = True
            db.session.add(student)
            db.session.flush()
            chapter = Chapter(name="Chương cho bài thi", teacher_id=teacher.id)
            db.session.add(chapter)
            db.session.flush()
            db.session.add(Exercise(
                chapter_id=chapter.id,
                title="Câu lấy từ chương",
                description="In số 1",
                generator_code="print(1)",
                solution_code="print(1)",
                num_test_cases=1,
                is_published=True,
            ))
            db.session.add(ExamChapterRule(
                exam_id=exam.id,
                chapter_id=chapter.id,
                question_count=1,
            ))
            db.session.flush()
            student_id = student.id
            exam_id = exam.id
            token = create_access_token(
                identity=str(student.id),
                additional_claims={"role": "student"},
            )
            db.session.commit()
        self.client.set_cookie("access_token_cookie", token)

        started = self.client.post(
            f"/api/student/exams/{exam_id}/start",
            json={"password": "exam-pass"},
        )
        self.assertEqual(started.status_code, 201)
        session_id = started.json["session_id"]

        workspace = self.client.get(f"/api/student/exam-sessions/{session_id}")
        self.assertEqual(workspace.status_code, 200)
        questions = workspace.json["exam"]["exercises"]
        self.assertEqual(len(questions), 1)
        self.assertTrue(questions[0]["id"].startswith("chapter-"))

        submission = self.client.post(
            f"/api/student/exam-sessions/{session_id}/submit",
            json={"exercise_id": questions[0]["id"], "code": "print(1)"},
        )
        self.assertEqual(submission.status_code, 200)
        self.assertEqual(submission.json["result"]["status"], "correct")

        with self.app.app_context():
            self.assertEqual(
                ExamSession.query.filter_by(id=session_id, user_id=student_id).count(),
                1,
            )

        exam_list = self.client.get("/api/student/exams")
        self.assertEqual(exam_list.status_code, 200)
        self.assertEqual(exam_list.json["exams"][0]["exercise_count"], 1)

        resumed_workspace = self.client.get(
            f"/api/student/exam-sessions/{session_id}"
        )
        self.assertEqual(
            resumed_workspace.json["exam"]["exercises"][0]["id"],
            questions[0]["id"],
        )
        self.assertEqual(
            resumed_workspace.json["submissions"][questions[0]["id"]]["status"],
            "correct",
        )

        with self.app.app_context():
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            teacher_token = create_access_token(
                identity=str(teacher.id),
                additional_claims={"role": "teacher"},
            )
        self.client.set_cookie("access_token_cookie", teacher_token)
        history = self.client.get(
            f"/api/teacher/students/{student_id}/exam-history"
        )
        self.assertEqual(history.status_code, 200)
        attempt = history.json["attempts"][0]
        self.assertEqual(attempt["question_count"], 1)
        self.assertEqual(attempt["submissions"][0]["code"], "print(1)")

    def test_chapter_always_shows_all_published_exercises(self):
        with self.app.app_context():
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            student = User(email="chapter-student@example.invalid", role="student")
            student.set_password("test-password")
            db.session.add(student)
            db.session.flush()
            chapter = Chapter(
                name="Chương cũ có chế độ ôn tập",
                teacher_id=teacher.id,
                mode="review",
            )
            db.session.add(chapter)
            db.session.flush()
            exercises = [
                Exercise(
                    chapter_id=chapter.id,
                    title=f"Bài {index}",
                    description="Câu hỏi",
                    is_published=True,
                )
                for index in range(7)
            ]
            db.session.add_all(exercises)
            session = ChapterSession(user_id=student.id, chapter_id=chapter.id)
            db.session.add(session)
            db.session.flush()
            chapter_id = chapter.id
            session_id = session.id
            token = create_access_token(
                identity=str(student.id),
                additional_claims={"role": "student"},
            )
            db.session.commit()
        self.client.set_cookie("access_token_cookie", token)

        chapter_data = self.client.get(f"/api/student/chapters/{chapter_id}")
        session_data = self.client.get(f"/api/student/sessions/{session_id}")
        self.assertEqual(chapter_data.status_code, 200)
        self.assertEqual(session_data.status_code, 200)
        self.assertEqual(len(chapter_data.json["chapter"]["exercises"]), 7)
        self.assertEqual(len(session_data.json["chapter"]["exercises"]), 7)
        self.assertEqual(chapter_data.json["chapter"]["mode"], "practice")
        self.assertEqual(session_data.json["chapter"]["mode"], "practice")

    def test_teacher_chapter_edit_no_longer_offers_random_review_mode(self):
        with self.app.app_context():
            teacher = User.query.filter_by(email="teacher-test@example.invalid").first()
            chapter = Chapter(
                name="Chương kiểm thử",
                teacher_id=teacher.id,
                mode="review",
            )
            db.session.add(chapter)
            db.session.commit()
            chapter_id = chapter.id
            token = create_access_token(
                identity=str(teacher.id),
                additional_claims={"role": "teacher"},
            )
        self.client.set_cookie("access_token_cookie", token)

        page = self.client.get(f"/teacher/chapters/{chapter_id}/edit")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(b"Random 5", page.data)
        self.assertNotIn(b'name="chapterMode"', page.data)

        updated = self.client.put(
            f"/api/chapters/{chapter_id}",
            json={"name": "Chương kiểm thử đã sửa", "mode": "review"},
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["chapter"]["mode"], "practice")

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
            connection.execute(
                "CREATE TABLE exam_sessions ("
                "id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, exam_id INTEGER NOT NULL, "
                "started_at DATETIME, finished_at DATETIME, is_finalized BOOLEAN)"
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
                session_columns = {
                    column["name"]
                    for column in inspect(engine).get_columns("exam_sessions")
                }
                row = db.session.execute(
                    text("SELECT max_attempts, password_hash, access_code FROM exams WHERE id = 10")
                ).one()
                db.session.remove()
                engine.dispose()
            self.assertTrue({"max_attempts", "password_hash", "access_code"}.issubset(columns))
            self.assertIn("question_ids", session_columns)
            self.assertEqual(row.max_attempts, 1)
            self.assertIsNone(row.password_hash)
            self.assertTrue(row.access_code)


if __name__ == "__main__":
    unittest.main()
