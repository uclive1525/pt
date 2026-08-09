from datetime import datetime
from zoneinfo import ZoneInfo

APP_TZ = ZoneInfo("Asia/Shanghai")
TZ_NAME = "Asia/Shanghai"


def now() -> datetime:
    return datetime.now(APP_TZ)


def now_str(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return now().strftime(fmt)


def now_hm() -> str:
    return now().strftime("%H:%M")


def fmt(dt: datetime, pattern: str = "%Y-%m-%d %H:%M:%S") -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=APP_TZ)
    else:
        dt = dt.astimezone(APP_TZ)
    return dt.strftime(pattern)
