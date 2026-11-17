from datetime import datetime, timedelta, timezone


VIETNAM_TZ = timezone(timedelta(hours=7))
UTC = timezone.utc


def vietnam_now_naive():
    return datetime.now(VIETNAM_TZ).replace(tzinfo=None)


def vietnam_aware(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=VIETNAM_TZ)
    return value.astimezone(VIETNAM_TZ)


def vietnam_local_naive(value):
    return vietnam_aware(value).replace(tzinfo=None)


def vietnam_datetime_local_value(value):
    if value is None:
        return ""
    return vietnam_aware(value).strftime("%Y-%m-%dT%H:%M")


def utc_now_naive():
    return datetime.now(UTC).replace(tzinfo=None)


def vietnam_iso(value):
    if value is None:
        return None
    return vietnam_aware(value).isoformat()


def utc_iso(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    else:
        value = value.astimezone(UTC)
    return value.isoformat()


def vietnam_elapsed_seconds(started_at, finished_at):
    if not started_at or not finished_at:
        return None
    start = (
        started_at.replace(tzinfo=VIETNAM_TZ)
        if started_at.tzinfo is None
        else started_at.astimezone(VIETNAM_TZ)
    )
    finish = (
        finished_at.replace(tzinfo=VIETNAM_TZ)
        if finished_at.tzinfo is None
        else finished_at.astimezone(VIETNAM_TZ)
    )
    return max(0, int((finish - start).total_seconds()))
