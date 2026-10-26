from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from app.config import get_settings


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().tz)).date()


def week_label(ws: date) -> str:
    """"Oct 26 to Nov 1" for the week starting ws."""
    we = ws + timedelta(days=6)
    if ws.month == we.month:
        return f"{ws:%b} {ws.day} to {we.day}"
    return f"{ws:%b} {ws.day} to {we:%b} {we.day}"
