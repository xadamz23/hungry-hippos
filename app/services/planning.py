"""Weekly plan: meals on days (or unscheduled), leftovers/eating-out nights, cook history."""

from dataclasses import dataclass
from datetime import date, timedelta

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.clock import today, week_label
from app.models import CookLog, Meal, PlanEntry
from app.services import shopping

KINDS = {"meal", "leftovers", "eat_out"}
KIND_LABELS = {"leftovers": "Leftovers", "eat_out": "Eating out"}


@dataclass
class WeekView:
    start: date
    days: list[tuple[date, list[PlanEntry]]]
    unscheduled: list[PlanEntry]
    pending_count: int

    @property
    def is_empty(self) -> bool:
        return not self.unscheduled and not any(entries for _, entries in self.days)


def week_start(d: date) -> date:
    """The Monday of d's week."""
    return d - timedelta(days=d.weekday())


def current_week() -> date:
    return week_start(today())


def get_entry(session: Session, entry_id: int) -> PlanEntry:
    entry = session.get(PlanEntry, entry_id)
    if entry is None:
        raise HTTPException(404, "That plan entry is gone.")
    return entry


def week(session: Session, ws: date) -> WeekView:
    entries = session.scalars(
        select(PlanEntry)
        .where(PlanEntry.week_start == ws)
        .options(selectinload(PlanEntry.meal))
        .order_by(PlanEntry.position, PlanEntry.id)
    ).all()
    days = [(ws + timedelta(days=i), []) for i in range(7)]
    by_day = dict(days)
    unscheduled = []
    for e in entries:
        (by_day[e.day] if e.day in by_day else unscheduled).append(e)
    pending = sum(1 for e in entries if e.kind == "meal" and e.meal is not None and not e.added_to_list)
    return WeekView(start=ws, days=days, unscheduled=unscheduled, pending_count=pending)


def entry_count(session: Session, ws: date) -> int:
    return session.scalar(select(func.count()).select_from(PlanEntry).where(PlanEntry.week_start == ws))


def add_entry(
    session: Session, ws: date, day: date | None, kind: str, meal_id: int | None = None, add_to_list: bool = False
) -> PlanEntry:
    if kind not in KINDS:
        raise HTTPException(400, "Unknown plan entry type.")
    meal = None
    if kind == "meal":
        meal = session.get(Meal, meal_id) if meal_id else None
        if meal is None:
            raise HTTPException(404, "That meal doesn't exist anymore.")
    ws = week_start(day) if day else ws
    position = session.scalar(select(func.coalesce(func.max(PlanEntry.position), -1)).where(PlanEntry.week_start == ws)) + 1
    entry = PlanEntry(week_start=ws, day=day, kind=kind, meal_id=meal.id if meal else None, position=position)
    session.add(entry)
    if meal is not None and add_to_list:
        entry.added_to_list = True
        shopping.add_meal(session, meal)  # commits
    session.commit()
    return entry


def move(session: Session, entry_id: int, day: date | None) -> PlanEntry:
    entry = get_entry(session, entry_id)
    entry.day = day
    if day is not None:
        entry.week_start = week_start(day)
    session.commit()
    return entry


def remove(session: Session, entry_id: int) -> None:
    session.delete(get_entry(session, entry_id))
    session.commit()


def add_week_to_list(session: Session, ws: date) -> int:
    view = week(session, ws)
    count = 0
    for entry in [e for _, entries in view.days for e in entries] + view.unscheduled:
        if entry.kind == "meal" and entry.meal is not None and not entry.added_to_list:
            shopping.add_meal(session, entry.meal)
            entry.added_to_list = True
            count += 1
    session.commit()
    return count


def mark_cooked(session: Session, entry_id: int, on: date) -> PlanEntry:
    """Toggle: log the meal as cooked on `on`, or undo that."""
    entry = get_entry(session, entry_id)
    if entry.cooked_on is not None:
        session.execute(delete(CookLog).where(CookLog.plan_entry_id == entry.id))
        entry.cooked_on = None
    else:
        entry.cooked_on = entry.day or on
        if entry.meal_id is not None:
            session.add(CookLog(meal_id=entry.meal_id, cooked_on=entry.cooked_on, plan_entry_id=entry.id))
    session.commit()
    return entry


def copy_week(session: Session, from_ws: date, to_ws: date) -> int | None:
    """Copy from_ws's entries into to_ws. None when to_ws already has entries (a second tap of Copy)."""
    if session.scalar(select(PlanEntry.id).where(PlanEntry.week_start == to_ws).limit(1)) is not None:
        return None
    source = session.scalars(select(PlanEntry).where(PlanEntry.week_start == from_ws).order_by(PlanEntry.position)).all()
    offset = to_ws - from_ws
    for pos, e in enumerate(source):
        session.add(
            PlanEntry(
                week_start=to_ws,
                day=e.day + offset if e.day else None,
                kind=e.kind,
                meal_id=e.meal_id,
                position=pos,
            )
        )
    session.commit()
    return len(source)


def history(session: Session, on: date | None = None, limit: int = 200) -> list[tuple[str, list]]:
    now_ws = week_start(on or today())
    times = dict(session.execute(select(CookLog.meal_id, func.count()).group_by(CookLog.meal_id)).all())
    logs = session.scalars(
        select(CookLog).options(selectinload(CookLog.meal)).order_by(CookLog.cooked_on.desc(), CookLog.id.desc()).limit(limit)
    ).all()
    groups: list[tuple[str, list]] = []
    for log in logs:
        ws = week_start(log.cooked_on)
        if ws == now_ws:
            label = "This week"
        elif ws == now_ws - timedelta(days=7):
            label = "Last week"
        else:
            label = week_label(ws)
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append((log.cooked_on, log.meal, times.get(log.meal_id, 0)))
    return groups
