from datetime import date
from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.assets import AssetManifest
from app.clock import today, week_label
from app.services import amounts
from app.services.sections import text_color

APP_DIR = Path(__file__).parent
STATIC_DIR = APP_DIR / "static"

manifest = AssetManifest(STATIC_DIR)
static_url = manifest.url


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


MEAL_GRADIENTS = [
    ("#F2B544", "#D9622B"), ("#F4E3B5", "#C9A35B"), ("#C8452E", "#7A2214"), ("#F7E07A", "#E39A3B"),
    ("#9C3B2A", "#5E2117"), ("#7FB069", "#3D6B35"), ("#E8A33D", "#8E4B12"), ("#6FA8A0", "#2F6158"),
]


def meal_bg(meal) -> str:
    """CSS background for a meal: its photo, or a warm gradient picked from its name."""
    if getattr(meal, "image_url", None):
        url = meal.image_url.replace('"', "%22").replace(")", "%29").replace("(", "%28")
        return f'center / cover no-repeat url("{url}")'
    a, b = MEAL_GRADIENTS[sum(map(ord, meal.name)) % len(MEAL_GRADIENTS)]
    return f"linear-gradient(135deg, {a}, {b})"


def cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def nice_day(d: date) -> str:
    return f"{d:%a} {d.day}"


templates = Jinja2Templates(directory=APP_DIR / "templates")
templates.env.globals.update(static_url=static_url, today=today)
templates.env.filters.update(
    amounts=amounts.fmt, text_color=text_color, cap=cap, meal_bg=meal_bg, ago=ago, nice_day=nice_day, week_label=week_label
)
