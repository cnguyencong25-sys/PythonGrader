import unittest
from collections import Counter
from datetime import timedelta

from flask_jwt_extended import create_access_token

from app import create_app
from extensions import db
from models import Chapter, Exercise, FreePracticeSession, User


class FreePracticeFlowTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app({
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "SECRET_KEY": "test-secret",
            "JWT_SECRET_KEY": "test-jwt-secret",
        })
        self.client = self.app.test_client()
        with self.app.app_context():
            teacher = User(email="free-practice-teacher@example.invalid", role="teacher")
            student = User(
                email="free-practice-student@example.invalid",
                role="student",
                profile_completed=True,
            )
            teacher.set_password("test-password")
            student.set_password("test-password")
            db.session.add_all([teacher, student])
            db.session.flush()

            self.chapter_ids = []
            self.exercise_chapters = {}
            for chapter_index, exercise_count in enumerate((1, 4, 4), start=1):
                chapter = Chapter(
                    name=f"Chương {chapter_index}",
                    teacher_id=teacher.id,
                )
                db.session.add(chapter)
                db.session.flush()
                self.chapter_ids.append(chapter.id)
                for exercise_index in range(exercise_count):
                    exercise = Exercise(
                        chapter_id=chapter.id,
                        title=f"Bài {chapter_index}-{exercise_index + 1}",
                        description="In số 1.",
                        generator_code="print(1)",
                        solution_code="print(1)",
                        num_test_cases=1,
                    )
                    db.session.add(exercise)
                    db.session.flush()
                    self.exercise_chapters[exercise.id] = chapter.id

            token = create_access_token(
                identity=str(student.id),
                additional_claims={"role": "student"},
            )
            db.session.commit()
        self.client.set_cookie("access_token_cookie", token)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def start_session(self, mode, chapter_ids, question_count, duration_minutes=None):
        payload = {
            "mode": mode,
            "chapter_ids": chapter_ids,
            "question_count": question_count,
        }
        if duration_minutes is not None:
            payload["duration_minutes"] = duration_minutes
        return self.client.post("/api/student/free-sessions/start", json=payload)

    def test_practice_session_is_untimed_and_uses_one_selected_chapter(self):
        selected_chapter = self.chapter_ids[1]
        started = self.start_session("practice", [selected_chapter], 2)

        self.assertEqual(started.status_code, 201)
        workspace = self.client.get(
            f"/api/student/free-sessions/{started.json['session_id']}"
        )
        self.assertEqual(workspace.status_code, 200)
        self.assertIsNone(workspace.json["remain_seconds"])
        self.assertEqual(len(workspace.json["exam"]["exercises"]), 2)
        self.assertTrue(all(
            self.exercise_chapters[int(question["id"].removeprefix("chapter-"))]
            == selected_chapter
            for question in workspace.json["exam"]["exercises"]
        ))
        question_key = workspace.json["exam"]["exercises"][0]["id"]
        code = 'value = input("Nhập: ")\nprint("Kết quả:", value)'
        waiting = self.client.post(
            f"/api/student/free-sessions/{started.json['session_id']}/run",
            json={"exercise_id": question_key, "code": code},
        )
        self.assertEqual(waiting.status_code, 200)
        self.assertTrue(waiting.json["needs_input"])
        self.assertEqual(waiting.json["stdout"], "Nhập: ")
        completed = self.client.post(
            f"/api/student/free-sessions/{started.json['session_id']}/run",
            json={
                "exercise_id": question_key,
                "code": code,
                "input": "đúng\n",
            },
        )
        self.assertEqual(completed.status_code, 200)
        self.assertFalse(completed.json["needs_input"])
        self.assertEqual(completed.json["stdout"], "Nhập: Kết quả: đúng\n")

        workspace_page = self.client.get(
            "/student/free-practice-workspace",
            query_string={"session_id": started.json["session_id"]},
        )
        self.assertEqual(workspace_page.status_code, 200)
        self.assertIn(b'data-session-mode="practice"', workspace_page.data)
        self.assertIn(b'id="clearRunOutputBtn"', workspace_page.data)
        self.assertIn(b'id="runInputForm"', workspace_page.data)
        self.assertIn(b'id="runInputTranscript"', workspace_page.data)
        self.assertNotIn(b"sendRunInputBtn", workspace_page.data)
        self.assertNotIn(b"official-exam-workspace", workspace_page.data)
        page = self.client.get("/student/chapters")
        self.assertEqual(page.status_code, 200)
        self.assertIn(
            b'id="simulationQuestionCount" type="number" min="1" step="1" value="5"',
            page.data,
        )
        chapter_picker_start = page.data.index(b'id="simulationChapterList"')
        question_count_start = page.data.index(b'id="simulationQuestionCount"')
        self.assertLess(
            chapter_picker_start,
            page.data.index(b'id="selectAllChapters"'),
        )
        self.assertLess(page.data.index(b'id="selectAllChapters"'), question_count_start)

    def test_run_executes_without_input_and_waits_for_sys_stdin_data(self):
        started = self.start_session("practice", [self.chapter_ids[0]], 1)
        question_key = f"chapter-{next(iter(self.exercise_chapters))}"

        no_input = self.client.post(
            f"/api/student/free-sessions/{started.json['session_id']}/run",
            json={"exercise_id": question_key, "code": 'print("ready")'},
        )
        self.assertEqual(no_input.status_code, 200)
        self.assertFalse(no_input.json["needs_input"])
        self.assertEqual(no_input.json["stdout"], "ready\n")

        for code in (
            "import sys\nprint(sys.stdin.read(), end='')",
            "from sys import stdin as source\nprint(source.read(), end='')",
        ):
            with self.subTest(code=code):
                waiting = self.client.post(
                    f"/api/student/free-sessions/{started.json['session_id']}/run",
                    json={"exercise_id": question_key, "code": code},
                )
                self.assertEqual(waiting.status_code, 200)
                self.assertTrue(waiting.json["needs_input"])
                self.assertEqual(waiting.json["stdout"], "")

                completed = self.client.post(
                    f"/api/student/free-sessions/{started.json['session_id']}/run",
                    json={
                        "exercise_id": question_key,
                        "code": code,
                        "input": "first line\nsecond line\n",
                    },
                )
                self.assertEqual(completed.status_code, 200)
                self.assertFalse(completed.json["needs_input"])
                self.assertEqual(completed.json["stdout"], "first line\nsecond line\n")

    def test_simulation_uses_distinct_chapters_when_k_is_at_least_n(self):
        for question_count in (3, 2):
            with self.subTest(question_count=question_count):
                started = self.start_session(
                    "simulation",
                    self.chapter_ids,
                    question_count=question_count,
                    duration_minutes=45,
                )
                self.assertEqual(started.status_code, 201)
                workspace = self.client.get(
                    f"/api/student/free-sessions/{started.json['session_id']}"
                )
                selected_questions = workspace.json["exam"]["exercises"]
                selected_chapters = [
                    self.exercise_chapters[
                        int(question["id"].removeprefix("chapter-"))
                    ]
                    for question in selected_questions
                ]
                self.assertEqual(len(selected_questions), question_count)
                self.assertEqual(len(set(selected_chapters)), question_count)

    def test_simulation_distributes_questions_and_auto_grades_saved_drafts(self):
        started = self.start_session(
            "simulation",
            self.chapter_ids,
            question_count=5,
            duration_minutes=12,
        )
        self.assertEqual(started.status_code, 201)

        session_id = started.json["session_id"]
        workspace = self.client.get(f"/api/student/free-sessions/{session_id}")
        self.assertEqual(workspace.status_code, 200)
        self.assertGreater(workspace.json["remain_seconds"], 0)
        self.assertLessEqual(workspace.json["remain_seconds"], 12 * 60)
        selected_questions = workspace.json["exam"]["exercises"]
        self.assertEqual(len(selected_questions), 5)
        chapter_counts = Counter(
            self.exercise_chapters[
                int(question["id"].removeprefix("chapter-"))
            ]
            for question in selected_questions
        )
        self.assertEqual(sorted(chapter_counts.values()), [1, 2, 2])

        question_key = selected_questions[0]["id"]
        saved = self.client.post(
            f"/api/student/free-sessions/{session_id}/save-draft",
            json={"exercise_id": question_key, "code": "print(1)"},
        )
        self.assertEqual(saved.status_code, 200)
        with self.app.app_context():
            session = db.session.get(FreePracticeSession, session_id)
            session.started_at -= timedelta(minutes=13)
            db.session.commit()
        finished = self.client.post(
            f"/api/student/free-sessions/{session_id}/finish",
            json={},
        )
        self.assertEqual(finished.status_code, 200)
        self.assertEqual(finished.json["submissions"][question_key]["status"], "correct")

        with self.app.app_context():
            session = db.session.get(FreePracticeSession, session_id)
            self.assertTrue(session.is_finalized)
            self.assertEqual(session.to_dict()["total_score"], 2.0)

    def test_start_rejects_invalid_scope_count_and_simulation_duration(self):
        too_many = self.start_session(
            "practice",
            [self.chapter_ids[0]],
            question_count=2,
        )
        self.assertEqual(too_many.status_code, 400)

        multiple_practice_chapters = self.start_session(
            "practice",
            self.chapter_ids[:2],
            question_count=1,
        )
        self.assertEqual(multiple_practice_chapters.status_code, 400)

        zero_duration = self.start_session(
            "simulation",
            [self.chapter_ids[0]],
            question_count=1,
            duration_minutes=0,
        )
        self.assertEqual(zero_duration.status_code, 400)


if __name__ == "__main__":
    unittest.main()
