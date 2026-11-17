import json
import unittest
from datetime import timedelta
from unittest.mock import patch

from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import Exam, PublicExamSession, PublicExamSubmission, User
from time_utils import vietnam_now_naive


class MockWebhookResponse:
    status = 200

    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self):
        return self.body


class GoogleSheetsExportTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            teacher = User(email="teacher@example.invalid", role="teacher")
            teacher.set_password("test-password")
            db.session.add(teacher)
            db.session.flush()
            exam = Exam(
                name="Bài thi xếp hạng",
                teacher_id=teacher.id,
                duration_minutes=60,
            )
            db.session.add(exam)
            db.session.commit()
            self.exam_id = exam.id
            token = create_access_token(
                identity=str(teacher.id),
                additional_claims={"role": "teacher"},
            )
        self.client.set_cookie("access_token_cookie", token)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def add_public_result(
        self, student_id, score, finished_minutes_ago, violations=0,
        code="print(1)", finished_at=None,
    ):
        with self.app.app_context():
            finished_at = finished_at or (
                vietnam_now_naive() - timedelta(minutes=finished_minutes_ago)
            )
            session = PublicExamSession(
                exam_id=self.exam_id,
                student_id=student_id,
                full_name=f"Sinh viên {student_id}",
                class_name="CTK44",
                session_token_hash=f"token-hash-{student_id}",
                attempt_number=1,
                question_ids='["exam-1"]',
                started_at=finished_at - timedelta(minutes=10),
                finished_at=finished_at,
                is_finalized=True,
                violation_count=violations,
            )
            db.session.add(session)
            db.session.flush()
            if code:
                db.session.add(PublicExamSubmission(
                    session_id=session.id,
                    question_key="exam-1",
                    code=code,
                    status="correct",
                    score=score,
                    max_score=10,
                ))
            db.session.commit()
            return finished_at

    def test_export_sends_ranked_report_and_returns_google_sheet_link(self):
        tie_time = self.add_public_result("SV001", 8, 2, violations=1)
        self.add_public_result("SV002", 10, 5)
        self.add_public_result("SV003", 10, 1)
        self.add_public_result("SV004", 0, 0, code="")
        self.add_public_result("SV005", 8, 2, finished_at=tie_time)
        response_body = json.dumps({
            "success": True,
            "spreadsheetUrl": "https://docs.google.com/spreadsheets/d/report-id/edit",
        }).encode("utf-8")

        with patch.dict("os.environ", {"GOOGLE_SHEETS_WEBHOOK_URL": "https://script.google.com/macros/s/test/exec"}):
            with patch("exams.urlopen", return_value=MockWebhookResponse(response_body)) as webhook:
                response = self.client.post(f"/api/exams/{self.exam_id}/export-sheet")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json["url"],
            "https://docs.google.com/spreadsheets/d/report-id/edit",
        )
        payload = json.loads(webhook.call_args.args[0].data.decode("utf-8"))
        self.assertEqual(payload["report"]["participant_count"], 5)
        self.assertEqual(payload["report"]["average_score"], 7.2)
        self.assertEqual(
            [row["student_id"] for row in payload["scores"]],
            ["SV002", "SV003", "SV005", "SV001", "SV004"],
        )
        self.assertEqual([row["rank"] for row in payload["scores"]], [1, 2, 3, 4, 5])
        self.assertEqual(payload["scores"][3]["status"], "Nghi vấn gian lận")
        self.assertEqual(payload["scores"][4]["status"], "Chưa nộp")
        self.assertTrue(payload["report"]["exported_at"].endswith("+07:00"))

    def test_export_rejects_webhook_response_without_a_google_sheet_url(self):
        self.add_public_result("SV001", 8, 1)
        response_body = json.dumps({"success": True}).encode("utf-8")
        with patch.dict("os.environ", {"GOOGLE_SHEETS_WEBHOOK_URL": "https://script.google.com/macros/s/test/exec"}):
            with patch("exams.urlopen", return_value=MockWebhookResponse(response_body)):
                response = self.client.post(f"/api/exams/{self.exam_id}/export-sheet")

        self.assertEqual(response.status_code, 502)
        self.assertIn("liên kết Google Sheets", response.json["message"])

    def test_export_requires_webhook_configuration(self):
        with patch("exams.os.getenv", return_value=""):
            response = self.client.post(f"/api/exams/{self.exam_id}/export-sheet")

        self.assertEqual(response.status_code, 503)


if __name__ == "__main__":
    unittest.main()
