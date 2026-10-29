import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.models import CookLog, Ingredient, Meal, MealPhoto, PlanEntry, Section, Tag, meal_tags
from app.services.amounts import fmt, scale
from app.services.ingredients import NAME_MAX, display_name, name_key, parse_line
from app.services.sections import guess_section, remember, staple_index


MEAL_NAME_MAX = 200
TAG_MAX = 60


def _tags(session: Session, names: list[str]) -> list[Tag]:
    out = []
    for raw in names:
        name = raw.strip()[:TAG_MAX].rstrip()
        if not name or any(t.name.lower() == name.lower() for t in out):
            continue
        tag = session.scalar(select(Tag).where(Tag.name.ilike(name)))
        if tag is None:
            tag = Tag(name=name)
            session.add(tag)
        out.append(tag)
    return out


PHOTO_MAX_BYTES = 10 * 1024 * 1024


def photo_url(photo: MealPhoto) -> str:
    return f"/meals/photos/{photo.id}"


PHOTO_URL = re.compile(r"/meals/photos/(\d+)")


def photo_id_from_url(url: str | None) -> int | None:
    """The id in an uploaded photo's address, or None for anything else (a web link, empty)."""
    m = PHOTO_URL.fullmatch(url or "")
    return int(m.group(1)) if m else None


def _owns_photo(session: Session, meal: Meal, url: str) -> bool:
    photo_id = photo_id_from_url(url)
    if photo_id is None:
        return True  # not an uploaded photo
    photo = session.get(MealPhoto, photo_id) if meal.id is not None and photo_id <= 2**31 - 1 else None
    return photo is not None and photo.meal_id == meal.id


def sniff_image(data: bytes) -> str | None:
    """The image type from the file's first bytes, so a renamed file can't be served as something else."""
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _drop_unused_photos(session: Session, meal: Meal) -> None:
    """Delete this meal's uploaded photos other than the one image_url points at."""
    if meal.id is None:
        return
    for photo in session.scalars(select(MealPhoto).where(MealPhoto.meal_id == meal.id)):
        if photo_url(photo) != meal.image_url:
            session.delete(photo)


def set_photo(session: Session, meal: Meal, data: bytes, content_type: str) -> None:
    """Make an uploaded photo the meal's picture, replacing any earlier one."""
    photo = MealPhoto(meal_id=meal.id, content_type=content_type, data=data)
    session.add(photo)
    session.flush()
    meal.image_url = photo_url(photo)
    _drop_unused_photos(session, meal)
    session.commit()


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
    meal.name = name.strip()[:MEAL_NAME_MAX].rstrip() or "Untitled meal"
    meal.steps = "\n".join(s.strip() for s in steps_text.splitlines() if s.strip())
    meal.notes = notes.strip()
    meal.tags = _tags(session, tags)
    meal.servings = servings
    meal.total_minutes = total_minutes
    meal.favorite = favorite
    if source_url is not None:
        meal.source_url = source_url or None
    # Another meal's uploaded photo is ignored: it would break when that meal changes or drops it
    if image_url is not None and _owns_photo(session, meal, image_url):
        meal.image_url = image_url or None
        _drop_unused_photos(session, meal)

    overrides = section_overrides or {}
    if overrides:
        sections = set(session.scalars(select(Section.id)))
        overrides = {pos: sid for pos, sid in overrides.items() if sid in sections}
    meal.ingredients.clear()
    session.flush()
    lines = [line.strip() for line in ingredients_text.splitlines() if line.strip()]
    staples = staple_index(session) if lines else None
    for pos, line in enumerate(lines):
        parsed = parse_line(line)
        if pos in overrides:
            section_id = overrides[pos]
            remember(session, parsed.name_key, section_id)
        else:
            section_id = guess_section(session, parsed.name_key, staples).id
        meal.ingredients.append(
            Ingredient(
                position=pos,
                raw=parsed.raw,
                name=(parsed.name or display_name(parsed.raw))[:NAME_MAX],
                name_key=(parsed.name_key or parsed.raw.lower())[:NAME_MAX],
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
