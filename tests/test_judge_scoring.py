import unittest
from unittest.mock import patch

from judge import evaluate_submission


class WeightedJudgeScoringTests(unittest.TestCase):
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
