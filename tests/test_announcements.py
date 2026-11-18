import unittest
from datetime import timedelta

from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import Announcement, User
from time_utils import utc_now_naive


class AnnouncementTests(unittest.TestCase):
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
                email="announcement-teacher@example.invalid",
                role="teacher",
                profile_completed=True,
            )
            teacher.set_password("test-password")
            student = User(
                email="announcement-student@example.invalid",
                role="student",
                profile_completed=True,
            )
            student.set_password("test-password")
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

    def test_teacher_broadcast_is_read_only_for_students_and_tracks_unread(self):
        self.use_role("student")
        denied_send = self.client.post(
            "/api/announcements", json={"content": "Không được gửi"}
        )
        self.assertEqual(denied_send.status_code, 403)

        self.use_role("teacher")
        sent = self.client.post(
            "/api/announcements", json={"content": "Lịch thi được cập nhật"}
        )
        self.assertEqual(sent.status_code, 201)
        announcement = sent.json["announcement"]
        self.assertTrue(announcement["created_at"])

        self.use_role("student")
        feed = self.client.get("/api/announcements")
        self.assertEqual(feed.status_code, 200)
        self.assertEqual(feed.json["unread_count"], 1)
        self.assertEqual(feed.json["announcements"][0]["content"], "Lịch thi được cập nhật")

        marked = self.client.post(
            "/api/announcements/read",
            json={"through_id": announcement["id"]},
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(marked.json["unread_count"], 0)

        self.use_role("teacher")
        second = self.client.post(
            "/api/announcements", json={"content": "Thông báo mới"}
        )
        self.assertEqual(second.status_code, 201)
        self.use_role("student")
        self.assertEqual(self.client.get("/api/announcements").json["unread_count"], 1)

    def test_expired_announcements_are_removed_when_loading_or_sending(self):
        with self.app.app_context():
            expired = Announcement(
                content="Thông báo cũ",
                created_at=utc_now_naive() - timedelta(hours=25),
            )
            db.session.add(expired)
            db.session.commit()
            expired_id = expired.id

        self.use_role("student")
        feed = self.client.get("/api/announcements")
        self.assertEqual(feed.json["announcements"], [])
        with self.app.app_context():
            self.assertIsNone(db.session.get(Announcement, expired_id))

        with self.app.app_context():
            expired = Announcement(
                content="Thông báo cũ thứ hai",
                created_at=utc_now_naive() - timedelta(hours=25),
            )
            db.session.add(expired)
            db.session.commit()
            expired_id = expired.id

        self.use_role("teacher")
        sent = self.client.post(
            "/api/announcements", json={"content": "Thông báo hiện tại"}
        )
        self.assertEqual(sent.status_code, 201)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Announcement, expired_id))

    def test_teacher_can_delete_but_student_cannot_and_ui_has_no_student_composer(self):
        self.use_role("teacher")
        sent = self.client.post(
            "/api/announcements", json={"content": "Có thể xóa"}
        )
        announcement_id = sent.json["announcement"]["id"]

        self.use_role("student")
        denied_delete = self.client.delete(f"/api/announcements/{announcement_id}")
        self.assertEqual(denied_delete.status_code, 403)
        student_page = self.client.get("/student/chapters")
        self.assertEqual(student_page.status_code, 200)
        self.assertNotIn(b"announcementForm", student_page.data)
        self.assertIn(b"announcementBadge", student_page.data)

        self.use_role("teacher")
        teacher_page = self.client.get("/teacher/chapters")
        self.assertEqual(teacher_page.status_code, 200)
        self.assertIn(b"announcementForm", teacher_page.data)
        removed = self.client.delete(f"/api/announcements/{announcement_id}")
        self.assertEqual(removed.status_code, 200)


if __name__ == "__main__":
    unittest.main()
