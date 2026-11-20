from extensions import db
from models import SystemSetting
from time_utils import utc_now_naive


REGISTRATION_BLOCKED = "registration_blocked"
STUDENT_LOGIN_MAINTENANCE = "student_login_maintenance"


def is_setting_enabled(key):
    setting = db.session.get(SystemSetting, key)
    return bool(setting and setting.value == "true")


def set_setting_enabled(key, enabled):
    setting = db.session.get(SystemSetting, key)
    if setting is None:
        setting = SystemSetting(key=key)
        db.session.add(setting)
    setting.value = "true" if enabled else "false"
    setting.updated_at = utc_now_naive()
    db.session.commit()
    return enabled
