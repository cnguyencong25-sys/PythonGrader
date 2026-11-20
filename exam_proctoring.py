from extensions import db
from models import ExamMonitoringRecord, ExamProctoringEvent
from time_utils import vietnam_now_naive


ABNORMAL_THRESHOLD = 5


def get_or_create_record(exam_id, user_id, session_id=None, device_id=None):
    record = ExamMonitoringRecord.query.filter_by(
        exam_id=exam_id,
        user_id=user_id,
    ).first()
    if not record:
        record = ExamMonitoringRecord(
            exam_id=exam_id,
            user_id=user_id,
            current_session_id=session_id,
            device_id=device_id,
        )
        db.session.add(record)
        db.session.flush()
    return record


def add_event(
    record,
    event_type,
    detail,
    session_id=None,
    abnormal=False,
    event_token=None,
):
    if abnormal:
        record.abnormal_count += 1
        if record.abnormal_count >= ABNORMAL_THRESHOLD:
            record.is_cheating = True

    event = ExamProctoringEvent(
        record_id=record.id,
        session_id=session_id,
        event_type=event_type,
        detail=detail,
        event_token=event_token,
        occurred_at=vietnam_now_naive(),
    )
    db.session.add(event)
    return event
