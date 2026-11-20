import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from flask_jwt_extended import create_access_token
from sqlalchemy import inspect, text

import student_api
from app import _upgrade_existing_schema, create_app
from extensions import db
from models import (
    Exam,
    ExamExercise,
    ExamMonitoringRecord,
    ExamProctoringEvent,
    ExamSession,
    User,
    VN_TZ,
)


class ExamProctoringTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            teacher = User(email="monitor-teacher@example.invalid", role="teacher")
            teacher.set_password("test-password")
            student = User(
                email="monitor-student@example.invalid",
                role="student",
                student_id="SV-MONITOR",
                full_name="Sinh viên giám sát",
                profile_completed=True,
            )
            untouched_student = User(
                email="monitor-untouched@example.invalid",
                role="student",
                student_id="SV-UNTOUCHED",
                full_name="Sinh viên chưa làm",
            )
            other_teacher = User(email="other-teacher@example.invalid", role="teacher")
            for user in (student, untouched_student, other_teacher):
                user.set_password("test-password")
            db.session.add_all([teacher, student, untouched_student, other_teacher])
            db.session.flush()

            self.exam = Exam(
                name="Bài thi giám sát",
                teacher_id=teacher.id,
                start_time=datetime.now(VN_TZ).replace(tzinfo=None) - timedelta(minutes=1),
                duration_minutes=30,
            )
            self.exam.set_exam_password("exam-pass")
            db.session.add(self.exam)
            db.session.flush()
            db.session.add(ExamExercise(
                exam_id=self.exam.id,
                title="Câu hỏi",
                description="In số 1",
                generator_code="print(1)",
                solution_code="print(1)",
                num_test_cases=1,
                is_published=True,
            ))
            self.exam_id = self.exam.id
            self.student_id = student.id
            self.untouched_student_id = untouched_student.id
            self.teacher_id = teacher.id
            self.other_teacher_id = other_teacher.id
            db.session.commit()

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

    def start_exam(self, device_id):
        return self.client.post(
            f"/api/student/exams/{self.exam_id}/start",
            json={"password": "exam-pass", "device_id": device_id},
        )

    def test_device_switch_threshold_monitoring_and_unblock(self):
        self.authenticate(self.student_id, "student")
        first = self.start_exam("device-a")
        self.assertEqual(first.status_code, 201)
        session_id = first.json["session_id"]

        same_device = self.start_exam("device-a")
        self.assertTrue(same_device.json["is_resumed"])
        self.assertEqual(same_device.json["abnormal_count"], 0)

        switched = self.start_exam("device-b")
        self.assertTrue(switched.json["device_changed"])
        self.assertEqual(switched.json["abnormal_count"], 1)

        switched_back = self.start_exam("device-a")
        self.assertTrue(switched_back.json["device_changed"])
        self.assertEqual(switched_back.json["abnormal_count"], 2)

        device_headers = {"X-Exam-Device-Id": "device-a"}
        for expected_count in range(3, 6):
            event = self.client.post(
                f"/api/student/exam-sessions/{session_id}/abnormal-event",
                json={"event_type": "focus_leave"},
                headers=device_headers,
            )
            self.assertEqual(event.status_code, 200)
            self.assertEqual(event.json["abnormal_count"], expected_count)
        self.assertTrue(event.json["is_cheating"])

        self.authenticate(self.teacher_id, "teacher")
        monitor = self.client.get(f"/api/exams/{self.exam_id}/monitor")
        participant = next(
            item for item in monitor.json["participants"]
            if item["user_id"] == self.student_id
        )
        self.assertEqual(participant["status"], "cheating")
        self.assertEqual(participant["abnormal_count"], 5)
        self.assertEqual(len(participant["events"]), 5)
        untouched = next(
            item for item in monitor.json["participants"]
            if item["user_id"] == self.untouched_student_id
        )
        self.assertEqual(untouched["status"], "not_started")

        blocked = self.client.post(
            f"/api/exams/{self.exam_id}/monitor/students/{self.student_id}/toggle-block"
        )
        self.assertTrue(blocked.json["is_blocked"])
        self.authenticate(self.student_id, "student")
        self.assertEqual(
            self.client.get(
                f"/api/student/exam-sessions/{session_id}",
                headers=device_headers,
            ).status_code,
            423,
        )
        self.authenticate(self.teacher_id, "teacher")
        scores = self.client.get(f"/api/exams/{self.exam_id}/scores")
        score_row = next(row for row in scores.json["scores"] if row["session_id"] == session_id)
        self.assertEqual(score_row["score"], 0.0)

        unblocked = self.client.post(
            f"/api/exams/{self.exam_id}/monitor/students/{self.student_id}/toggle-block"
        )
        self.assertFalse(unblocked.json["is_blocked"])
        self.assertFalse(unblocked.json["is_cheating"])
        self.assertEqual(unblocked.json["abnormal_count"], 5)

        self.authenticate(self.student_id, "student")
        next_event = self.client.post(
            f"/api/student/exam-sessions/{session_id}/abnormal-event",
            json={"event_type": "focus_leave"},
            headers=device_headers,
        )
        self.assertEqual(next_event.json["abnormal_count"], 6)
        self.assertTrue(next_event.json["is_cheating"])

        with self.app.app_context():
            record = ExamMonitoringRecord.query.filter_by(
                exam_id=self.exam_id, user_id=self.student_id
            ).one()
            self.assertEqual(ExamProctoringEvent.query.filter_by(record_id=record.id).count(), 8)
            self.assertEqual(ExamSession.query.filter_by(id=session_id).count(), 1)

    def test_teacher_ownership_and_blocking_before_first_attempt(self):
        self.authenticate(self.other_teacher_id, "teacher")
        denied = self.client.get(f"/api/exams/{self.exam_id}/monitor")
        self.assertEqual(denied.status_code, 404)

        self.authenticate(self.teacher_id, "teacher")
        blocked = self.client.post(
            f"/api/exams/{self.exam_id}/monitor/students/"
            f"{self.untouched_student_id}/toggle-block"
        )
        self.assertEqual(blocked.status_code, 200)
        self.assertTrue(blocked.json["is_blocked"])
        self.assertEqual(
            next(
                item for item in self.client.get(
                    f"/api/exams/{self.exam_id}/monitor"
                ).json["participants"]
                if item["user_id"] == self.untouched_student_id
            )["status"],
            "cheating",
        )

        self.authenticate(self.untouched_student_id, "student")
        start = self.start_exam("device-new")
        self.assertEqual(start.status_code, 423)
        blocked_resume = self.client.post(
            "/api/student/exams/active-session",
            json={"device_id": "device-new"},
        )
        self.assertEqual(blocked_resume.status_code, 200)
        self.assertFalse(blocked_resume.json["active"])

        self.authenticate(self.teacher_id, "teacher")
        unblocked = self.client.post(
            f"/api/exams/{self.exam_id}/monitor/students/"
            f"{self.untouched_student_id}/toggle-block"
        )
        self.assertFalse(unblocked.json["is_blocked"])
        self.assertEqual(unblocked.json["abnormal_count"], 0)

    def test_disabled_anti_cheat_skips_device_checks_and_proctoring(self):
        with self.app.app_context():
            exam = db.session.get(Exam, self.exam_id)
            exam.anti_cheat_enabled = False
            db.session.commit()

            existing_record = ExamMonitoringRecord(
                exam_id=self.exam_id,
                user_id=self.student_id,
                is_blocked=True,
                is_cheating=True,
                abnormal_count=4,
            )
            db.session.add(existing_record)
            db.session.commit()

        self.authenticate(self.student_id, "student")
        started = self.client.post(
            f"/api/student/exams/{self.exam_id}/start",
            json={"password": "exam-pass"},
        )
        self.assertEqual(started.status_code, 201)
        self.assertFalse(started.json["anti_cheat_enabled"])
        session_id = started.json["session_id"]

        resumed = self.client.post("/api/student/exams/active-session", json={})
        self.assertEqual(resumed.status_code, 200)
        self.assertTrue(resumed.json["active"])
        self.assertFalse(resumed.json["anti_cheat_enabled"])

        workspace = self.client.get(
            f"/api/student/exam-sessions/{session_id}"
        )
        self.assertEqual(workspace.status_code, 200)
        self.assertFalse(workspace.json["exam"]["anti_cheat_enabled"])
        self.assertEqual(workspace.json["abnormal_count"], 0)
        status = self.client.get(
            f"/api/student/exam-sessions/{session_id}/status"
        )
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json["is_blocked"])
        self.assertEqual(status.json["abnormal_count"], 0)

        event = self.client.post(
            f"/api/student/exam-sessions/{session_id}/abnormal-event",
            json={"event_type": "focus_leave"},
        )
        self.assertEqual(event.status_code, 200)
        self.assertTrue(event.json["ignored"])

        self.authenticate(self.teacher_id, "teacher")
        monitor = self.client.get(f"/api/exams/{self.exam_id}/monitor")
        self.assertEqual(monitor.status_code, 403)
        block = self.client.post(
            f"/api/exams/{self.exam_id}/monitor/students/"
            f"{self.student_id}/toggle-block"
        )
        self.assertEqual(block.status_code, 403)

        self.authenticate(self.untouched_student_id, "student")
        started = self.start_exam("device-new")
        self.assertEqual(started.status_code, 201)

    def test_blocking_a_finished_exam_temporarily_zeroes_and_restores_score(self):
        self.authenticate(self.student_id, "student")
        started = self.start_exam("device-a")
        session_id = started.json["session_id"]
        workspace = self.client.get(
            f"/api/student/exam-sessions/{session_id}",
            headers={"X-Exam-Device-Id": "device-a"},
        )
        question_id = workspace.json["exam"]["exercises"][0]["id"]
        submitted = self.client.post(
            f"/api/student/exam-sessions/{session_id}/submit",
            json={"exercise_id": question_id, "code": "print(1)"},
            headers={"X-Exam-Device-Id": "device-a"},
        )
        self.assertEqual(submitted.json["result"]["status"], "correct")
        finished = self.client.post(
            f"/api/student/exam-sessions/{session_id}/finish",
            headers={"X-Exam-Device-Id": "device-a"},
        )
        self.assertEqual(finished.status_code, 200)

        self.authenticate(self.teacher_id, "teacher")
        block_url = (
            f"/api/exams/{self.exam_id}/monitor/students/"
            f"{self.student_id}/toggle-block"
        )
        self.client.post(block_url)
        blocked_score = self.client.get(f"/api/exams/{self.exam_id}/scores")
        row = next(item for item in blocked_score.json["scores"] if item["session_id"] == session_id)
        self.assertEqual(row["score"], 0.0)
        self.assertEqual(row["status"], "Gian lận")

        self.client.post(block_url)
        restored_score = self.client.get(f"/api/exams/{self.exam_id}/scores")
        row = next(item for item in restored_score.json["scores"] if item["session_id"] == session_id)
        self.assertEqual(row["score"], 10.0)
        self.assertEqual(row["status"], "Hoàn thành")

    def test_second_browser_login_can_resume_exam_after_revoking_first_login(self):
        first_browser = self.app.test_client()
        second_browser = self.app.test_client()
        credentials = {
            "email": "monitor-student@example.invalid",
            "password": "test-password",
        }
        first_login = first_browser.post("/api/auth/login", json=credentials)
        self.assertEqual(first_login.status_code, 200)
        first_exam = first_browser.post(
            f"/api/student/exams/{self.exam_id}/start",
            json={"password": "exam-pass", "device_id": "first-browser"},
        )
        self.assertEqual(first_exam.status_code, 201)

        second_login = second_browser.post("/api/auth/login", json=credentials)
        self.assertEqual(second_login.status_code, 200)
        resumed_home = second_browser.get("/")
        self.assertEqual(resumed_home.status_code, 302)
        self.assertEqual(resumed_home.location, "/student/dashboard")
        self.assertEqual(
            first_browser.get("/api/student/exams").status_code,
            401,
        )
        self.assertEqual(second_browser.get("/api/student/exams").status_code, 200)

        started = second_browser.post(
            f"/api/student/exams/{self.exam_id}/start",
            json={"password": "exam-pass", "device_id": "private-browser"},
        )
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json["is_resumed"])
        self.assertTrue(started.json["device_changed"])
        self.assertEqual(started.json["abnormal_count"], 1)
        self.assertEqual(started.json["session_id"], first_exam.json["session_id"])
        workspace = second_browser.get(
            f"/api/student/exam-sessions/{started.json['session_id']}",
            headers={"X-Exam-Device-Id": "private-browser"},
        )
        self.assertEqual(workspace.status_code, 200)
        workspace_page = second_browser.get(
            "/student/exam-workspace",
            query_string={"session_id": started.json["session_id"]},
        )
        self.assertEqual(workspace_page.status_code, 200)
        self.assertIn(b"official-exam-workspace", workspace_page.data)
        self.assertIn(b"ws-theme-toggle", workspace_page.data)
        self.assertIn(b"data-theme-toggle", workspace_page.data)

    def test_active_exam_resume_counts_once_and_uses_focus_event_to_avoid_duplicates(self):
        self.authenticate(self.student_id, "student")
        started = self.start_exam("resume-device")
        session_id = started.json["session_id"]
        headers = {"X-Exam-Device-Id": "resume-device"}
        event_token = "0123456789abcdef0123456789abcdef"

        focus_leave = self.client.post(
            f"/api/student/exam-sessions/{session_id}/abnormal-event",
            json={"event_type": "focus_leave", "event_token": event_token},
            headers=headers,
        )
        self.assertEqual(focus_leave.status_code, 200)
        self.assertEqual(focus_leave.json["abnormal_count"], 1)

        resumed_after_focus = self.client.post(
            "/api/student/exams/active-session",
            json={
                "device_id": "resume-device",
                "prior_focus_event_token": event_token,
            },
        )
        self.assertEqual(resumed_after_focus.status_code, 200)
        self.assertTrue(resumed_after_focus.json["active"])
        self.assertEqual(resumed_after_focus.json["abnormal_count"], 1)

        retried_resume = self.client.post(
            "/api/student/exams/active-session",
            json={
                "device_id": "resume-device",
                "prior_focus_event_token": event_token,
            },
        )
        self.assertEqual(retried_resume.json["abnormal_count"], 1)

        resumed_again = self.client.post(
            "/api/student/exams/active-session",
            json={"device_id": "resume-device"},
        )
        self.assertEqual(resumed_again.status_code, 200)
        self.assertEqual(resumed_again.json["abnormal_count"], 2)

        with self.app.app_context():
            record = ExamMonitoringRecord.query.filter_by(
                exam_id=self.exam_id,
                user_id=self.student_id,
            ).one()
            resume_events = ExamProctoringEvent.query.filter_by(
                record_id=record.id,
                event_type="exam_resume",
            ).all()
            self.assertEqual(len(resume_events), 1)
            self.assertEqual(record.abnormal_count, 2)

    def test_resume_and_focus_event_race_counts_a_single_violation(self):
        self.authenticate(self.student_id, "student")
        started = self.start_exam("race-device")
        session_id = started.json["session_id"]
        resume_token = "fedcba9876543210fedcba9876543210"

        resumed_first = self.client.post(
            "/api/student/exams/active-session",
            json={
                "device_id": "race-device",
                "prior_focus_event_token": resume_token,
            },
        )
        self.assertEqual(resumed_first.status_code, 200)
        self.assertEqual(resumed_first.json["abnormal_count"], 1)

        def miss_first_lookup():
            original_lookup = student_api._exam_exit_event_for_token
            first_lookup = True

            def lookup(record, event_session_id, event_token):
                nonlocal first_lookup
                if first_lookup:
                    first_lookup = False
                    return None
                return original_lookup(record, event_session_id, event_token)

            return lookup

        with patch(
            "student_api._exam_exit_event_for_token",
            side_effect=miss_first_lookup(),
        ):
            delayed_focus_event = self.client.post(
                f"/api/student/exam-sessions/{session_id}/abnormal-event",
                json={
                    "event_type": "focus_leave",
                    "event_token": resume_token,
                },
                headers={"X-Exam-Device-Id": "race-device"},
            )
        self.assertEqual(delayed_focus_event.status_code, 200)
        self.assertTrue(delayed_focus_event.json["deduplicated"])
        self.assertEqual(delayed_focus_event.json["abnormal_count"], 1)

        focus_token = "0123456789abcdef0123456789abcdef"
        first_focus_event = self.client.post(
            f"/api/student/exam-sessions/{session_id}/abnormal-event",
            json={"event_type": "focus_leave", "event_token": focus_token},
            headers={"X-Exam-Device-Id": "race-device"},
        )
        self.assertEqual(first_focus_event.json["abnormal_count"], 2)
        with patch(
            "student_api._exam_exit_event_for_token",
            side_effect=miss_first_lookup(),
        ):
            resumed_after_focus = self.client.post(
                "/api/student/exams/active-session",
                json={
                    "device_id": "race-device",
                    "prior_focus_event_token": focus_token,
                },
            )
        self.assertEqual(resumed_after_focus.status_code, 200)
        self.assertEqual(resumed_after_focus.json["abnormal_count"], 2)

        with self.app.app_context():
            record = ExamMonitoringRecord.query.filter_by(
                exam_id=self.exam_id,
                user_id=self.student_id,
            ).one()
            self.assertEqual(record.abnormal_count, 2)
            self.assertEqual(
                ExamProctoringEvent.query.filter_by(record_id=record.id).count(),
                2,
            )

    def test_expired_jwt_clears_cookies_and_redirects_pages_to_login(self):
        self.assertEqual(
            self.app.config["JWT_ACCESS_TOKEN_EXPIRES"],
            12 * 60 * 60,
        )
        with self.app.app_context():
            token = create_access_token(
                identity=str(self.student_id),
                additional_claims={"role": "student"},
                expires_delta=timedelta(seconds=-1),
            )

        api_client = self.app.test_client()
        api_client.set_cookie("access_token_cookie", token)
        api_response = api_client.get("/api/auth/me")
        self.assertEqual(api_response.status_code, 401)
        self.assertEqual(api_response.json["msg"], "Token has expired")
        self.assertTrue(any(
            "access_token_cookie=;" in value
            for value in api_response.headers.getlist("Set-Cookie")
        ))

        page_client = self.app.test_client()
        page_client.set_cookie("access_token_cookie", token)
        page_response = page_client.get("/student/dashboard")
        self.assertEqual(page_response.status_code, 302)
        self.assertEqual(page_response.location, "/login?expired=token")
        self.assertTrue(any(
            "access_token_cookie=;" in value
            for value in page_response.headers.getlist("Set-Cookie")
        ))
        login_page = page_client.get(page_response.location)
        self.assertIn(
            "Phiên đăng nhập đã hết hạn, vui lòng đăng nhập lại".encode(),
            login_page.data,
        )

    def test_existing_proctoring_tables_are_upgraded_without_losing_records(self):
        with self.app.app_context():
            db.session.execute(text("DROP TABLE exam_proctoring_events"))
            db.session.execute(text("DROP TABLE exam_monitoring_records"))
            db.session.execute(text(
                "CREATE TABLE exam_monitoring_records ("
                "id INTEGER PRIMARY KEY, exam_id INTEGER NOT NULL, "
                "user_id INTEGER NOT NULL, current_session_id INTEGER, "
                "device_id VARCHAR(64), abnormal_count INTEGER NOT NULL DEFAULT 0, "
                "is_blocked BOOLEAN NOT NULL DEFAULT 0, "
                "is_cheating BOOLEAN NOT NULL DEFAULT 0)"
            ))
            db.session.execute(text(
                "INSERT INTO exam_monitoring_records "
                "(id, exam_id, user_id, device_id, abnormal_count) "
                "VALUES (101, :exam_id, :user_id, 'legacy-device', 3)"
            ), {"exam_id": self.exam_id, "user_id": self.student_id})
            db.session.execute(text(
                "CREATE TABLE exam_proctoring_events "
                "(id INTEGER PRIMARY KEY, record_id INTEGER NOT NULL)"
            ))
            db.session.execute(text(
                "INSERT INTO exam_proctoring_events (id, record_id) VALUES (202, 101)"
            ))
            db.session.commit()
            db.session.remove()

            db.create_all()
            _upgrade_existing_schema()
            _upgrade_existing_schema()
            columns = {
                column["name"]
                for column in inspect(db.engine).get_columns("exam_monitoring_records")
            }
            event_columns = {
                column["name"]
                for column in inspect(db.engine).get_columns("exam_proctoring_events")
            }
            self.assertIn("blocked_at", columns)
            self.assertIn("updated_at", columns)
            self.assertIn("event_token", event_columns)
            event_indexes = inspect(db.engine).get_indexes("exam_proctoring_events")
            self.assertTrue(any(
                index["name"] == "uq_exam_proctoring_event_token"
                and index["unique"]
                for index in event_indexes
            ))
            record = db.session.get(ExamMonitoringRecord, 101)
            self.assertEqual(record.device_id, "legacy-device")
            self.assertEqual(record.abnormal_count, 3)
            self.assertIsNone(record.blocked_at)
            self.assertIsNotNone(record.updated_at)
            self.assertTrue(inspect(db.engine).has_table("exam_proctoring_events"))
            event = db.session.get(ExamProctoringEvent, 202)
            self.assertEqual(event.event_type, "legacy_event")
            self.assertEqual(event.detail, "")
            self.assertIsNone(event.event_token)
            self.assertIsNotNone(event.occurred_at)

        self.authenticate(self.teacher_id, "teacher")
        monitor = self.client.get(f"/api/exams/{self.exam_id}/monitor")
        self.assertEqual(monitor.status_code, 200)
        self.assertTrue(monitor.json["success"])

        self.authenticate(self.student_id, "student")
        started = self.start_exam("migrated-device")
        self.assertEqual(started.status_code, 201)
