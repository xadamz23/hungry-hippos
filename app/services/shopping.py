"""The shared shopping list: adding with merge, checking off, grouping in walk order."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.models import ListItem, ListItemSource, Meal, Section, Staple
from app.services import amounts as amt
from app.services.ingredients import name_key, parse_line
from app.services import sections

CHANNEL = "hh_list"


def notify(session: Session) -> None:
    session.execute(text("SELECT pg_notify(:ch, 'changed')"), {"ch": CHANNEL})


def _commit(session: Session) -> None:
    notify(session)
    session.commit()


def get_item(session: Session, item_id: int) -> ListItem:
    item = session.get(ListItem, item_id)
    if item is None:
        raise HTTPException(404, "That item is no longer on the list.")
    return item


def _add(session, name, key, amounts, section_id=None, source: Meal | None = None) -> ListItem:
    item = session.scalar(
        select(ListItem).where(ListItem.name_key == key, ListItem.checked.is_(False)).limit(1)
    )
    if item is None:
        if section_id is None:
            section_id = sections.guess_section(session, key).id
        item = ListItem(name=name, name_key=key, amounts=list(amounts), section_id=section_id)
        session.add(item)
    else:
        item.amounts = amt.merge(item.amounts, amounts)
    if source is not None and not any(s.meal_id == source.id for s in item.sources):
        item.sources.append(ListItemSource(meal_id=source.id, meal_name=source.name))
    return item


def add_item(session, name: str, amounts: list, section_id: int | None = None, source: Meal | None = None) -> ListItem:
    item = _add(session, name, name_key(name), amounts, section_id, source)
    _commit(session)
    return item


def add_text(session: Session, text_: str) -> ListItem | None:
    parsed = parse_line(text_)
    name = parsed.name or parsed.raw
    if not name:
        return None
    amounts = [{"qty": parsed.qty, "unit": parsed.unit}] if parsed.qty is not None else []
    return add_item(session, name, amounts)


def add_meal(session: Session, meal: Meal, factor: float = 1.0) -> int:
    for ing in meal.ingredients:
        _add(session, ing.name, ing.name_key, amt.scale(ing.amounts, factor), ing.section_id, meal)
    _commit(session)
    return len(meal.ingredients)


def available_staples(session: Session) -> list[Staple]:
    on_list = set(session.scalars(select(ListItem.name_key).where(ListItem.checked.is_(False))))
    staples = session.scalars(select(Staple).order_by(Staple.position, Staple.id)).all()
    return [s for s in staples if s.name_key not in on_list]


def add_staple(session: Session, staple_id: int) -> ListItem:
    staple = session.get(Staple, staple_id)
    if staple is None:
        raise HTTPException(404, "That staple no longer exists.")
    item = _add(session, staple.name, staple.name_key, staple.amounts, staple.section_id)
    _commit(session)
    return item


def toggle(session: Session, item_id: int) -> ListItem:
    item = get_item(session, item_id)
    item.checked = not item.checked
    item.checked_at = datetime.now(UTC) if item.checked else None
    _commit(session)
    return item


def update(session: Session, item_id: int, amount_text: str, section_id: int, remember: bool) -> ListItem:
    item = get_item(session, item_id)
    item.amounts = amt.parse_amount_text(amount_text)
    if session.get(Section, section_id) is not None:
        item.section_id = section_id
        if remember:
            sections.remember(session, item.name_key, section_id)
    _commit(session)
    return item


def remove(session: Session, item_id: int) -> None:
    session.delete(get_item(session, item_id))
    _commit(session)


def clear_checked(session: Session) -> int:
    n = session.execute(delete(ListItem).where(ListItem.checked.is_(True))).rowcount
    _commit(session)
    return n


def clear_all(session: Session) -> int:
    n = session.execute(delete(ListItem)).rowcount
    _commit(session)
    return n


def grouped(session: Session) -> list[tuple[Section, list[ListItem]]]:
    items = session.scalars(select(ListItem).order_by(ListItem.checked, ListItem.created_at, ListItem.id)).all()
    all_sections = session.scalars(select(Section).order_by(Section.position, Section.id)).all()
    by_section: dict[int | None, list[ListItem]] = {}
    for item in items:
        by_section.setdefault(item.section_id, []).append(item)
    out = [(s, by_section.pop(s.id)) for s in all_sections if s.id in by_section]
    orphans = [i for group in by_section.values() for i in group]  # their section was deleted
    if orphans:
        other = next((s for s in all_sections if s.name == sections.OTHER), all_sections[-1])
        for sec, group in out:
            if sec.id == other.id:
                group.extend(orphans)
                break
        else:
            out.append((other, orphans))
    return out


def progress(session: Session) -> tuple[int, int]:
    items = session.scalars(select(ListItem.checked)).all()
    return sum(1 for c in items if not c), len(items)
