import os
import sqlite3
import tempfile
import unittest

from flask_jwt_extended import create_access_token
from sqlalchemy import inspect, text

from app import create_app
from extensions import db
from models import Chapter, ChapterSession, ChapterSubmission, Exercise, User


class ChapterVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            self.teacher = User(email="visibility-teacher@example.invalid", role="teacher")
            self.student = User(
                email="visibility-student@example.invalid",
                role="student",
                profile_completed=True,
            )
            self.teacher.set_password("test-password")
            self.student.set_password("test-password")
            db.session.add_all([self.teacher, self.student])
            db.session.flush()
            self.student_id = self.student.id
            chapter = Chapter(name="Chương tạm ẩn", teacher_id=self.teacher.id)
            db.session.add(chapter)
            db.session.flush()
            self.chapter_id = chapter.id
            exercise = Exercise(
                chapter_id=chapter.id,
                title="Bài công khai",
                description="In số 1.",
                is_published=True,
            )
            db.session.add(exercise)
            db.session.flush()
            self.exercise_id = exercise.id
            self.teacher_token = create_access_token(
                identity=str(self.teacher.id),
                additional_claims={"role": "teacher"},
            )
            self.student_token = create_access_token(
                identity=str(self.student.id),
                additional_claims={"role": "student"},
            )
            db.session.commit()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def use_role(self, role):
        token = self.teacher_token if role == "teacher" else self.student_token
        self.client.set_cookie("access_token_cookie", token)

    def test_teacher_can_hide_and_restore_chapter_for_students(self):
        self.use_role("teacher")
        hidden = self.client.post(
            f"/api/chapters/{self.chapter_id}/toggle-visibility"
        )
        self.assertEqual(hidden.status_code, 200)
        self.assertTrue(hidden.json["is_hidden"])

        teacher_list = self.client.get("/api/chapters")
        self.assertTrue(teacher_list.json["chapters"][0]["is_hidden"])

        self.use_role("student")
        self.assertEqual(self.client.get("/api/student/chapters").json["chapters"], [])
        self.assertEqual(
            self.client.get(f"/api/student/chapters/{self.chapter_id}").status_code,
            404,
        )
        self.assertEqual(
            self.client.get(
                f"/student/chapters/{self.chapter_id}"
            ).status_code,
            302,
        )
        self.assertEqual(
            self.client.post(f"/api/student/chapters/{self.chapter_id}/start").status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                "/api/student/free-sessions/start",
                json={
                    "mode": "practice",
                    "chapter_ids": [self.chapter_id],
                    "question_count": 1,
                },
            ).status_code,
            404,
        )

        self.use_role("teacher")
        restored = self.client.post(
            f"/api/chapters/{self.chapter_id}/toggle-visibility"
        )
        self.assertEqual(restored.status_code, 200)
        self.assertFalse(restored.json["is_hidden"])

        self.use_role("student")
        self.assertEqual(
            [chapter["id"] for chapter in self.client.get(
                "/api/student/chapters"
            ).json["chapters"]],
            [self.chapter_id],
        )
        self.assertEqual(
            self.client.post(f"/api/student/chapters/{self.chapter_id}/start").status_code,
            201,
        )

    def test_teacher_cannot_toggle_another_teachers_chapter(self):
        with self.app.app_context():
            other_teacher = User(
                email="other-visibility-teacher@example.invalid",
                role="teacher",
            )
            other_teacher.set_password("test-password")
            db.session.add(other_teacher)
            db.session.flush()
            token = create_access_token(
                identity=str(other_teacher.id),
                additional_claims={"role": "teacher"},
            )
            db.session.commit()

        self.client.set_cookie("access_token_cookie", token)
        response = self.client.post(
            f"/api/chapters/{self.chapter_id}/toggle-visibility"
        )
        self.assertEqual(response.status_code, 404)

        with self.app.app_context():
            chapter = db.session.get(Chapter, self.chapter_id)
            self.assertFalse(chapter.is_hidden)

    def test_existing_chapter_table_is_upgraded_with_visibility_column(self):
        with tempfile.TemporaryDirectory() as directory:
            database_path = os.path.join(directory, "legacy.sqlite3")
            connection = sqlite3.connect(database_path)
            connection.execute(
                "CREATE TABLE chapters ("
                "id INTEGER PRIMARY KEY, name VARCHAR(200) NOT NULL, "
                "mode VARCHAR(20) NOT NULL DEFAULT 'practice', "
                "teacher_id INTEGER NOT NULL, created_at DATETIME)"
            )
            connection.execute(
                "INSERT INTO chapters (id, name, teacher_id) VALUES (10, 'Legacy', 1)"
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
                columns = {
                    column["name"]
                    for column in inspect(db.engine).get_columns("chapters")
                }
                row = db.session.execute(
                    text("SELECT is_hidden FROM chapters WHERE id = 10")
                ).one()
                engine = db.engine
                db.session.remove()
                engine.dispose()

        self.assertIn("is_hidden", columns)
        self.assertFalse(row.is_hidden)

    def test_teacher_can_hide_and_restore_an_exercise_for_students(self):
        self.use_role("teacher")
        hidden = self.client.post(
                f"/api/chapters/exercises/{self.exercise_id}/toggle-publish"
        )
        self.assertEqual(hidden.status_code, 200)
        self.assertFalse(hidden.json["is_published"])

        self.use_role("student")
        chapters = self.client.get("/api/student/chapters").json["chapters"]
        self.assertEqual(chapters[0]["total_exercises"], 0)
        chapter = self.client.get(
                f"/api/student/chapters/{self.chapter_id}"
        ).json["chapter"]
        self.assertEqual(chapter["exercises"], [])

        self.use_role("teacher")
        restored = self.client.post(
                f"/api/chapters/exercises/{self.exercise_id}/toggle-publish"
        )
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(restored.json["is_published"])

        self.use_role("student")
        chapter = self.client.get(
                f"/api/student/chapters/{self.chapter_id}"
        ).json["chapter"]
        self.assertEqual(
                [exercise["id"] for exercise in chapter["exercises"]],
                [self.exercise_id],
        )


    def test_student_chapter_list_reports_completed_exercises(self):
        self.use_role("student")
        chapter_list = self.client.get("/api/student/chapters").json["chapters"]
        self.assertEqual(chapter_list[0]["completed_exercises"], 0)

        with self.app.app_context():
            session = ChapterSession(
                user_id=self.student_id,
                chapter_id=self.chapter_id,
            )
            db.session.add(session)
            db.session.flush()
            db.session.add(ChapterSubmission(
                session_id=session.id,
                exercise_id=self.exercise_id,
                status="correct",
            ))
            repeat_session = ChapterSession(
                user_id=self.student_id,
                chapter_id=self.chapter_id,
            )
            db.session.add(repeat_session)
            db.session.flush()
            db.session.add(ChapterSubmission(
                session_id=repeat_session.id,
                exercise_id=self.exercise_id,
                status="correct",
            ))
            db.session.commit()

        chapter_list = self.client.get("/api/student/chapters").json["chapters"]
        self.assertEqual(chapter_list[0]["completed_exercises"], 1)


if __name__ == "__main__":
    unittest.main()
