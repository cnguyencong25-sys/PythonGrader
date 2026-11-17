import unittest

from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import User


class StudentProfileTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            student = User(
                email="student@example.invalid",
                role="student",
                full_name="Nguyen Van A",
                student_id="SV001",
                class_name="CTK44",
                profile_completed=True,
            )
            student.set_password("InitialSecret#123")
            teacher = User(email="teacher@example.invalid", role="teacher")
            teacher.set_password("TeacherSecret#123")
            duplicate = User(
                email="duplicate@example.invalid",
                role="student",
                student_id="SV002",
            )
            duplicate.set_password("InitialSecret#123")
            db.session.add_all([student, teacher, duplicate])
            db.session.commit()
            self.student_id = student.id
            self.teacher_id = teacher.id
        self.authenticate(self.student_id, "student")

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def authenticate(self, user_id, role):
        with self.app.app_context():
            token = create_access_token(
                identity=str(user_id),
                additional_claims={"role": role},
            )
        self.client.set_cookie("access_token_cookie", token)

    def test_profile_page_and_profile_update(self):
        page = self.client.get("/student/profile")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b'id="studentThemeToggle"', page.data)
        self.assertIn(b"/static/js/student_theme.js", page.data)
        self.assertIn(b'id="profileEmail" type="email"', page.data)
        self.assertIn(b"readonly", page.data)
        self.assertIn(b'id="changePasswordForm"', page.data)
        self.assertNotIn(b"InitialSecret#123", page.data)

        updated = self.client.put(
            "/api/auth/student-profile",
            json={
                "full_name": "  Nguyen Van B  ",
                "student_id": "SV101",
                "class_name": "CTK45",
                "email": "changed@example.invalid",
            },
        )
        self.assertEqual(updated.status_code, 200)
        self.assertEqual(updated.json["user"]["full_name"], "Nguyen Van B")
        self.assertEqual(updated.json["user"]["student_id"], "SV101")
        self.assertEqual(updated.json["user"]["class_name"], "CTK45")
        self.assertEqual(updated.json["user"]["email"], "student@example.invalid")
        self.assertNotIn("password_hash", updated.json["user"])

    def test_profile_update_rejects_missing_invalid_and_duplicate_values(self):
        missing = self.client.put(
            "/api/auth/student-profile",
            json={"full_name": "", "student_id": "SV101", "class_name": "CTK45"},
        )
        self.assertEqual(missing.status_code, 400)

        invalid_id = self.client.put(
            "/api/auth/student-profile",
            json={
                "full_name": "Nguyen Van B",
                "student_id": "SV 101",
                "class_name": "CTK45",
            },
        )
        self.assertEqual(invalid_id.status_code, 400)

        duplicate = self.client.put(
            "/api/auth/student-profile",
            json={
                "full_name": "Nguyen Van B",
                "student_id": "SV002",
                "class_name": "CTK45",
            },
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_password_change_checks_old_password_confirmation_and_updates_hash(self):
        wrong_current = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "WrongPassword",
                "new_password": "NewSecret#123",
                "confirm_password": "NewSecret#123",
            },
        )
        self.assertEqual(wrong_current.status_code, 400)

        mismatch = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "InitialSecret#123",
                "new_password": "NewSecret#123",
                "confirm_password": "OtherSecret#123",
            },
        )
        self.assertEqual(mismatch.status_code, 400)

        too_long = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "InitialSecret#123",
                "new_password": "A" * 73,
                "confirm_password": "A" * 73,
            },
        )
        self.assertEqual(too_long.status_code, 400)

        changed = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "InitialSecret#123",
                "new_password": "NewSecret#123",
                "confirm_password": "NewSecret#123",
            },
        )
        self.assertEqual(changed.status_code, 200)
        self.assertTrue(changed.json["success"])
        with self.app.app_context():
            student = db.session.get(User, self.student_id)
            self.assertTrue(student.check_password("NewSecret#123"))
            self.assertFalse(student.check_password("InitialSecret#123"))

    def test_teacher_cannot_use_student_profile_endpoints(self):
        self.authenticate(self.teacher_id, "teacher")
        profile_update = self.client.put(
            "/api/auth/student-profile",
            json={
                "full_name": "Teacher Name",
                "student_id": "SV900",
                "class_name": "CTK45",
            },
        )
        password_change = self.client.post(
            "/api/auth/change-password",
            json={
                "current_password": "TeacherSecret#123",
                "new_password": "NewSecret#123",
                "confirm_password": "NewSecret#123",
            },
        )
        self.assertEqual(profile_update.status_code, 403)
        self.assertEqual(password_change.status_code, 403)


if __name__ == "__main__":
    unittest.main()
