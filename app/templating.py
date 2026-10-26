from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi.templating import Jinja2Templates

from app.assets import AssetManifest
from app.config import get_settings
from app.services import amounts
from app.services.sections import text_color

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"

manifest = AssetManifest(STATIC_DIR)
static_url = manifest.url


def today() -> date:
    return datetime.now(ZoneInfo(get_settings().tz)).date()


def ago(d: date | None) -> str:
    if d is None:
        return "never"
    days = (today() - d).days
    if days <= 0:
        return "today"
    if days == 1:
        return "yesterday"
    if days < 7:
        return f"{days} days ago"
    if days < 14:
        return "a week ago"
    if days < 30:
        return f"{days // 7} weeks ago"
    if days < 60:
        return "a month ago"
    if days < 365:
        return f"{days // 30} months ago"
    return "over a year ago"


def nice_day(d: date) -> str:
    return f"{d:%a} {d.day}"


def week_label(ws: date) -> str:
    we = date.fromordinal(ws.toordinal() + 6)
    if ws.month == we.month:
        return f"{ws:%b} {ws.day} to {we.day}"
    return f"{ws:%b} {ws.day} to {we:%b} {we.day}"


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals.update(static_url=static_url, today=today)
templates.env.filters.update(
    amounts=amounts.fmt, text_color=text_color, ago=ago, nice_day=nice_day, week_label=week_label
)
