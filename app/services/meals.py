from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import CookLog, Ingredient, Meal, PlanEntry, Tag, meal_tags
from app.services.amounts import fmt, scale
from app.services.ingredients import display_name, name_key, parse_line
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
                name=parsed.name or display_name(parsed.raw),
                name_key=parsed.name_key or parsed.raw.lower(),
                amounts=[{"qty": parsed.qty, "unit": parsed.unit}] if parsed.qty is not None else [],
                section_id=section_id,
            )
        )
    session.commit()
    return meal


@dataclass
class MealRow:
    meal: Meal
    last_made: date | None
    times_made: int
    planned_on: PlanEntry | None = None


def search(
    session: Session,
    q: str | None = None,
    favorites: bool = False,
    tag: str | None = None,
    pick_mode: bool = False,
    week_start: date | None = None,
) -> list[MealRow]:
    stats = (
        select(CookLog.meal_id, func.max(CookLog.cooked_on).label("last"), func.count().label("n"))
        .group_by(CookLog.meal_id)
        .subquery()
    )
    stmt = (
        select(Meal, stats.c.last, stats.c.n)
        .outerjoin(stats, stats.c.meal_id == Meal.id)
        .options(selectinload(Meal.tags))
    )
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            or_(Meal.name.ilike(like), Meal.ingredients.any(Ingredient.name.ilike(like)), Meal.tags.any(Tag.name.ilike(like)))
        )
    if favorites:
        stmt = stmt.where(Meal.favorite.is_(True))
    if tag:
        stmt = stmt.where(Meal.tags.any(Tag.name == tag))
    if pick_mode:
        stmt = stmt.order_by(Meal.favorite.desc(), stats.c.last.asc().nulls_first(), func.lower(Meal.name))
    else:
        stmt = stmt.order_by(func.lower(Meal.name))
    rows = [MealRow(meal=m, last_made=last, times_made=n or 0) for m, last, n in session.execute(stmt)]
    if week_start is not None and rows:
        planned = session.scalars(
            select(PlanEntry)
            .where(PlanEntry.week_start == week_start, PlanEntry.meal_id.in_([r.meal.id for r in rows]))
            .order_by(PlanEntry.day.asc().nulls_last(), PlanEntry.id)
        ).all()
        by_meal: dict[int, PlanEntry] = {}
        for p in planned:
            by_meal.setdefault(p.meal_id, p)
        for r in rows:
            r.planned_on = by_meal.get(r.meal.id)
        if pick_mode:  # already planned this week: least useful suggestions
            rows.sort(key=lambda r: r.planned_on is not None)
    return rows


def stats_for(session: Session, meal_id: int) -> tuple[date | None, int]:
    last, n = session.execute(
        select(func.max(CookLog.cooked_on), func.count()).where(CookLog.meal_id == meal_id)
    ).one()
    return last, n


def all_tags(session: Session) -> list[str]:
    return list(session.scalars(select(Tag.name).where(Tag.id.in_(select(meal_tags.c.tag_id))).order_by(Tag.name)))


def ingredients_for_step(meal: Meal, step_text: str, factor: float) -> list[tuple[str, str]]:
    """Ingredients a step mentions, with scaled amounts."""
    step_key = f" {name_key(step_text)} "
    out = []
    for ing in meal.ingredients:
        words = ing.name_key.split()
        # match the full name, or its last word ("the onions" for "yellow onion")
        if words and (f" {ing.name_key} " in step_key or f" {words[-1]} " in step_key):
            out.append((ing.name[:1].upper() + ing.name[1:], fmt(scale(ing.amounts, factor))))
    return out
