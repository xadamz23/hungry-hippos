"""The shared shopping list: adding with merge, checking off, grouping in walk order."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy import delete, select, text
from sqlalchemy import update as sql_update
from sqlalchemy.orm import Session, selectinload

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


def _from_meal(item: ListItem, meal: Meal | None) -> bool:
    if meal is None:
        return not item.sources
    return any(s.meal_id == meal.id for s in item.sources)


def _add(session, name, key, amounts, section_id=None, source: Meal | None = None) -> ListItem:
    # Each meal keeps its own rows, and typed items never merge into a meal's rows.
    candidates = session.scalars(
        select(ListItem).where(ListItem.name_key == key, ListItem.checked.is_(False)).order_by(ListItem.id)
    ).all()
    item = next((i for i in candidates if _from_meal(i, source)), None)
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


def _count_staple_add(session: Session, key: str) -> None:
    session.execute(sql_update(Staple).where(Staple.name_key == key).values(add_count=Staple.add_count + 1))


def add_text(session: Session, text_: str) -> ListItem | None:
    parsed = parse_line(text_)
    name = parsed.name or parsed.raw
    if not name:
        return None
    _count_staple_add(session, name_key(name))
    amounts = [{"qty": parsed.qty, "unit": parsed.unit}] if parsed.qty is not None else []
    return add_item(session, name, amounts)


def add_meal(session: Session, meal: Meal, factor: float = 1.0) -> int:
    for ing in meal.ingredients:
        _add(session, ing.name, ing.name_key, amt.scale(ing.amounts, factor), ing.section_id, meal)
    _commit(session)
    return len(meal.ingredients)


def all_staples(session: Session) -> list[Staple]:
    # Most-added first; the manual order on More > Staples breaks ties.
    return session.scalars(
        select(Staple).options(selectinload(Staple.section)).order_by(Staple.add_count.desc(), Staple.position, Staple.id)
    ).all()


def available_staples(session: Session) -> list[Staple]:
    on_list = set(session.scalars(select(ListItem.name_key).where(ListItem.checked.is_(False))))
    return [s for s in all_staples(session) if s.name_key not in on_list]


def add_staple(session: Session, staple_id: int) -> ListItem:
    staple = session.get(Staple, staple_id)
    if staple is None:
        raise HTTPException(404, "That favorite no longer exists.")
    staple.add_count += 1
    item = _add(session, staple.name, staple.name_key, staple.amounts, staple.section_id)
    _commit(session)
    return item


def toggle(session: Session, item_id: int) -> ListItem:
    item = get_item(session, item_id)
    item.checked = not item.checked
    item.checked_at = datetime.now(UTC) if item.checked else None
    _commit(session)
    return item


def update(session: Session, item_id: int, amount_text: str, note: str) -> ListItem:
    item = get_item(session, item_id)
    item.amounts = amt.parse_amount_text(amount_text)
    item.note = note.strip() or None
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


def _list_items(session: Session) -> list[ListItem]:
    return session.scalars(select(ListItem).order_by(ListItem.checked, ListItem.created_at, ListItem.id)).all()


def meal_groups(session: Session) -> list[tuple[str, list[ListItem]]]:
    """Items added from a meal, one group per meal (oldest first), each in walk order."""
    by_meal: dict[object, tuple[str, list[ListItem]]] = {}
    for item in _list_items(session):
        if not item.sources:
            continue
        src = item.sources[0]  # older lists may have merged several meals into one row
        key = src.meal_id if src.meal_id is not None else src.meal_name  # the meal may have been deleted
        by_meal.setdefault(key, (src.meal_name, []))[1].append(item)
    out = []
    for name, items in sorted(by_meal.values(), key=lambda g: min(i.id for i in g[1])):
        items.sort(key=lambda i: (i.checked, i.section.position if i.section else 1_000_000))
        out.append((name, items))
    return out


def grouped(session: Session) -> list[tuple[Section, list[ListItem]]]:
    """Items not from a meal, grouped by store section in walk order."""
    items = [i for i in _list_items(session) if not i.sources]
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
