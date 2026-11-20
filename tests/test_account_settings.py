import unittest

from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import SystemSetting, User, UserSession
from system_settings import REGISTRATION_BLOCKED, STUDENT_LOGIN_MAINTENANCE


class AccountSettingsTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            teacher = User(
                email="account-settings-teacher@example.invalid",
                role="teacher",
                profile_completed=True,
            )
            teacher.set_password("teacher-password")
            student = User(
                email="account-settings-student@example.invalid",
                role="student",
                profile_completed=True,
            )
            student.set_password("student-password")
            db.session.add_all([teacher, student])
            db.session.flush()
            self.teacher_id = teacher.id
            self.student_id = student.id
            self.teacher_token = create_access_token(
                identity=str(teacher.id),
                additional_claims={"role": "teacher"},
            )
            self.student_token = create_access_token(
                identity=str(student.id),
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

    def set_setting(self, key, enabled):
        return self.client.put(
            "/api/teacher/account-settings",
            json={"key": key, "enabled": enabled},
        )

    def test_teacher_can_toggle_registration_and_maintenance(self):
        self.use_role("teacher")
        page = self.client.get("/teacher/accounts")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"T\xc3\xa0i Kho\xe1\xba\xa3n", page.data)

        initial = self.client.get("/api/teacher/account-settings")
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json["settings"][REGISTRATION_BLOCKED])
        self.assertFalse(initial.json["settings"][STUDENT_LOGIN_MAINTENANCE])

        blocked = self.set_setting(REGISTRATION_BLOCKED, True)
        self.assertEqual(blocked.status_code, 200)
        registration = self.client.post(
            "/api/auth/register",
            json={
                "email": "new-student@example.invalid",
                "password": "student-password",
                "confirm_password": "student-password",
            },
        )
        self.assertEqual(registration.status_code, 403)
        self.assertIn("không cho phép tạo tài khoản", registration.json["message"])

        with self.app.app_context():
            self.assertEqual(
                SystemSetting.query.filter_by(key=REGISTRATION_BLOCKED).one().value,
                "true",
            )

    def test_maintenance_blocks_only_student_login_and_can_be_disabled(self):
        self.use_role("teacher")
        enabled = self.set_setting(STUDENT_LOGIN_MAINTENANCE, True)
        self.assertEqual(enabled.status_code, 200)

        student_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "account-settings-student@example.invalid",
                "password": "student-password",
            },
        )
        self.assertEqual(student_login.status_code, 503)
        self.assertEqual(
            student_login.json["message"],
            "Server đang bảo trì tạm thời, quay lại sau nhé",
        )
        with self.app.app_context():
            self.assertEqual(
                UserSession.query.filter_by(user_id=self.student_id).count(),
                0,
            )

        registration_during_maintenance = self.client.post(
            "/api/auth/register",
            json={
                "email": "maintenance-student@example.invalid",
                "password": "student-password",
                "confirm_password": "student-password",
            },
        )
        self.assertEqual(registration_during_maintenance.status_code, 503)
        self.assertEqual(
            registration_during_maintenance.json["message"],
            "Server đang bảo trì tạm thời, quay lại sau nhé",
        )
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(
                email="maintenance-student@example.invalid"
            ).first())

        teacher_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "account-settings-teacher@example.invalid",
                "password": "teacher-password",
            },
        )
        self.assertEqual(teacher_login.status_code, 200)

        self.use_role("teacher")
        disabled = self.set_setting(STUDENT_LOGIN_MAINTENANCE, False)
        self.assertEqual(disabled.status_code, 200)
        student_login = self.client.post(
            "/api/auth/login",
            json={
                "email": "account-settings-student@example.invalid",
                "password": "student-password",
            },
        )
        self.assertEqual(student_login.status_code, 200)

    def test_students_cannot_read_or_change_account_controls(self):
        self.use_role("student")
        read_settings = self.client.get("/api/teacher/account-settings")
        update_settings = self.set_setting(REGISTRATION_BLOCKED, True)
        self.assertEqual(read_settings.status_code, 403)
        self.assertEqual(update_settings.status_code, 403)
