import unittest
from datetime import datetime, timedelta, timezone

from models import ChapterSession, ExamSession
from time_utils import (
    utc_iso,
    vietnam_datetime_local_value,
    vietnam_elapsed_seconds,
    vietnam_iso,
    vietnam_local_naive,
)


class TimeUtilityTests(unittest.TestCase):
    def test_serializers_attach_or_convert_explicit_timezones(self):
        vietnam_local = datetime(2026, 6, 10, 17, 0)
        utc_aware = datetime(2026, 6, 10, 10, 0, tzinfo=timezone.utc)

        self.assertEqual(vietnam_iso(vietnam_local), "2026-06-10T17:00:00+07:00")
        self.assertEqual(vietnam_iso(utc_aware), "2026-06-10T17:00:00+07:00")
        vietnam_aware = vietnam_local.replace(tzinfo=timezone(timedelta(hours=7)))
        self.assertEqual(utc_iso(vietnam_aware), "2026-06-10T10:00:00+00:00")

    def test_vietnam_local_datetime_inputs_preserve_wall_clock_time(self):
        stored_utc = datetime(2026, 11, 16, 18, 56, tzinfo=timezone.utc)
        local_naive = datetime(2026, 11, 17, 1, 56)

        self.assertEqual(
            vietnam_datetime_local_value(stored_utc),
            "2026-11-17T01:56",
        )
        self.assertEqual(
            vietnam_local_naive(stored_utc),
            local_naive,
        )
        self.assertEqual(
            vietnam_iso(stored_utc),
            "2026-11-17T01:56:00+07:00",
        )

    def test_elapsed_time_uses_vietnam_wall_clock_values(self):
        started_at = datetime(2026, 6, 10, 17, 0)
        finished_at = datetime(2026, 6, 10, 10, 1, tzinfo=timezone.utc)

        self.assertEqual(vietnam_elapsed_seconds(started_at, finished_at), 60)
        self.assertIsNone(vietnam_elapsed_seconds(started_at, None))

    def test_session_serializers_declare_their_storage_timezone(self):
        practice_session = ChapterSession(
            started_at=datetime(2026, 6, 10, 10, 0),
            finished_at=datetime(2026, 6, 10, 11, 0),
        )
        exam_session = ExamSession(
            started_at=datetime(2026, 6, 10, 17, 0),
            finished_at=datetime(2026, 6, 10, 18, 0),
        )

        self.assertTrue(practice_session.to_dict()["started_at"].endswith("+00:00"))
        self.assertTrue(exam_session.to_dict()["started_at"].endswith("+07:00"))


if __name__ == "__main__":
    unittest.main()
