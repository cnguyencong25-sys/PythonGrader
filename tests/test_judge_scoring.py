import json
import os
import unittest
from unittest.mock import patch

from judge import evaluate_submission, run_python_code


class WeightedJudgeScoringTests(unittest.TestCase):
    def test_run_python_code_preserves_utf8_input_and_output(self):
        stdout, stderr = run_python_code(
            'import sys\n'
            'value = input()\n'
            'print("Kết quả:", value)\n'
            'print("Lỗi:", value, file=sys.stderr)',
            "đúng",
        )

        self.assertEqual(stdout, "Kết quả: đúng\n")
        self.assertEqual(stderr, "Lỗi: đúng\n")

    def test_student_process_does_not_inherit_server_secrets_or_working_directory(self):
        parent_directory = os.getcwd()
        server_values = {
            "SECRET_KEY": "test-secret-value",
            "JWT_SECRET_KEY": "test-jwt-secret-value",
            "DATABASE_URL": "test-database-connection-value",
            "MAIL_PASSWORD": "test-mail-password-value",
        }
        code = (
            "import json, os\n"
            "print(json.dumps(dict(os.environ)))\n"
            "print(os.getcwd())\n"
        )

        with patch.dict(os.environ, server_values):
            stdout, stderr = run_python_code(code, "")

        self.assertEqual(stderr, "")
        child_environment_json, child_directory = stdout.splitlines()
        child_environment = json.loads(child_environment_json)
        for key in server_values:
            self.assertNotIn(key, child_environment)
        for value in server_values.values():
            self.assertNotIn(value, child_environment_json)
        self.assertEqual(child_environment["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(child_environment["PYTHONUTF8"], "1")
        self.assertNotEqual(child_directory, parent_directory)
        self.assertTrue(os.path.basename(child_directory).startswith("python-grader-"))

    def test_weighted_full_partial_and_zero_scores(self):
        test_cases = {
            "correct": (["1", "2"], 5.0),
            "partial": (["1", "0"], 2.5),
            "wrong": (["0", "0"], 0.0),
        }

        for expected_status, (student_outputs, expected_score) in test_cases.items():
            with self.subTest(status=expected_status):
                run_results = []
                for test_input, student_output in zip(("1", "2"), student_outputs):
                    run_results.extend([
                        (f"{test_input}\n", ""),
                        (f"{test_input}\n", ""),
                        (f"{student_output}\n", ""),
                    ])

                with patch("judge.run_python_code", side_effect=run_results):
                    result = evaluate_submission(
                        student_code="student code",
                        generator_code="generator",
                        solution_code="solution",
                        num_tests=2,
                        max_score=5.0,
                    )

                self.assertEqual(result["status"], expected_status)
                self.assertEqual(result["score"], expected_score)
                self.assertEqual(result["max_score"], 5.0)

    def test_blank_or_whitespace_submission_is_wrong_without_running_tests(self):
        for student_code in ("", " \t\n "):
            with self.subTest(student_code=student_code):
                with patch("judge.run_python_code") as run_code:
                    result = evaluate_submission(
                        student_code=student_code,
                        generator_code="generator",
                        solution_code="solution",
                        num_tests=20,
                        max_score=2.5,
                    )

                self.assertEqual(result, {
                    "status": "wrong",
                    "score": 0.0,
                    "max_score": 2.5,
                    "passed": 0,
                    "total": 20,
                })
                run_code.assert_not_called()


if __name__ == "__main__":
    unittest.main()
