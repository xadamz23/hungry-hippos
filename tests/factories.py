from sqlalchemy import select

from app.models import Meal, Section
from app.services.meals import save_meal


def section(session, name):
    return session.scalar(select(Section).where(Section.name == name))


def make_meal(session, name="Tacos", ingredients="1 lb ground beef\n1 yellow onion", **kw) -> Meal:
    defaults = dict(
        meal=None, name=name, ingredients_text=ingredients, steps_text=kw.pop("steps_text", ""),
        notes="", tags=kw.pop("tags", []), servings=kw.pop("servings", 4), total_minutes=None,
        favorite=kw.pop("favorite", False),
    )
    defaults.update(kw)
    return save_meal(session, **defaults)
