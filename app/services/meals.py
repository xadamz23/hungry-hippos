from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Ingredient, Meal, Tag
from app.services.ingredients import parse_line
from app.services.sections import guess_section, remember


def _tags(session: Session, names: list[str]) -> list[Tag]:
    out = []
    for raw in names:
        name = raw.strip()
        if not name or any(t.name.lower() == name.lower() for t in out):
            continue
        tag = session.scalar(select(Tag).where(Tag.name.ilike(name)))
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
        out.append(tag)
    return out


def save_meal(
    session: Session,
    *,
    meal: Meal | None,
    name: str,
    ingredients_text: str,
    steps_text: str,
    notes: str,
    tags: list[str],
    servings: int | None,
    total_minutes: int | None,
    favorite: bool,
    source_url: str | None = None,
    image_url: str | None = None,
    section_overrides: dict[int, int] | None = None,
) -> Meal:
    """Create or update a meal, re-parsing every ingredient line."""
    if meal is None:
        meal = Meal()
        session.add(meal)
    meal.name = name.strip() or "Untitled meal"
    meal.steps = "\n".join(s.strip() for s in steps_text.splitlines() if s.strip())
    meal.notes = notes.strip()
    meal.tags = _tags(session, tags)
    meal.servings = servings
    meal.total_minutes = total_minutes
    meal.favorite = favorite
    if source_url is not None:
        meal.source_url = source_url or None
    if image_url is not None:
        meal.image_url = image_url or None

    overrides = section_overrides or {}
    meal.ingredients.clear()
    session.flush()
    lines = [line.strip() for line in ingredients_text.splitlines() if line.strip()]
    for pos, line in enumerate(lines):
        parsed = parse_line(line)
        if pos in overrides:
            section_id = overrides[pos]
            remember(session, parsed.name_key, section_id)
        else:
            section_id = guess_section(session, parsed.name_key).id
        meal.ingredients.append(
            Ingredient(
                position=pos,
                raw=parsed.raw,
                name=parsed.name or parsed.raw,
                name_key=parsed.name_key or parsed.raw.lower(),
                amounts=[{"qty": parsed.qty, "unit": parsed.unit}] if parsed.qty is not None else [],
                section_id=section_id,
            )
        )
    session.commit()
    return meal
