import json
from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.clock import today
from app.db import get_session
from app.routers.list import items_response, list_context
from app.routers.meals import get_meal
from app.services import planning
from app.templating import templates

router = APIRouter()


def _ws(week: date | None) -> date:
    return planning.week_start(week) if week else planning.current_week()


def _parse_day(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value and value != "none" else None
    except ValueError:
        return None


def plan_context(session: Session, ws: date) -> dict:
    prev = ws - timedelta(days=7)
    return {
        "view": planning.week(session, ws),
        "prev_week": prev,
        "next_week": ws + timedelta(days=7),
        "prev_count": planning.entry_count(session, prev),
        "kind_labels": planning.KIND_LABELS,
    }


def week_response(request: Request, session: Session, ws: date, *, toast: str | None = None, close_sheet=False):
    response = templates.TemplateResponse(request, "plan/_week.html", plan_context(session, ws))
    triggers = {}
    if toast:
        triggers["toast"] = toast
    if close_sheet:
        triggers["close-sheet"] = True
    if triggers:
        response.headers["HX-Trigger"] = json.dumps(triggers)
    return response


@router.get("/plan")
def plan_page(request: Request, week: date | None = None, session: Session = Depends(get_session)):
    ws = _ws(week)
    return templates.TemplateResponse(
        request, "plan/page.html", {"active": "plan", **plan_context(session, ws), **list_context(session)}
    )


@router.get("/plan/day-sheet")
def day_sheet(request: Request, day: str = "none", week: date | None = None):
    d = _parse_day(day)
    return templates.TemplateResponse(request, "plan/_day_sheet.html", {"day": d, "week": _ws(d or week)})


def _when(day: date | None, ws: date) -> str:
    if day:
        return f"Planned for {day:%A}" if planning.week_start(day) == planning.current_week() else f"Planned for {day:%a %b} {day.day}"
    if ws == planning.current_week():
        return "Planned for this week"
    return f"Planned for the week of {ws:%b} {ws.day}"


@router.post("/plan/entries")
def add_entry(
    request: Request,
    week: date | None = Form(None),
    day: str = Form(""),
    kind: str = Form("meal"),
    meal_id: int | None = Form(None),
    add_to_list: str | None = Form(None),
    next: str = Form("plan"),
    session: Session = Depends(get_session),
):
    d = _parse_day(day)
    ws = _ws(d or week)
    entry = planning.add_entry(session, ws, d, kind, meal_id, add_to_list=bool(add_to_list))
    message = _when(d, ws) + (" and added to the list" if entry.added_to_list else "")
    if next == "stay":
        return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": message, "close-sheet": True})})
    if next == "week":
        return week_response(request, session, ws, close_sheet=True)
    url = f"/plan?week={ws}"
    if request.headers.get("HX-Request"):
        return Response(status_code=204, headers={"HX-Redirect": url})
    return RedirectResponse(url, status_code=303)


@router.get("/plan/entries/{entry_id}/sheet")
def entry_sheet(request: Request, entry_id: int, session: Session = Depends(get_session)):
    entry = planning.get_entry(session, entry_id)
    view = planning.week(session, entry.week_start)
    return templates.TemplateResponse(
        request, "plan/_entry_sheet.html", {"entry": entry, "view": view, "kind_labels": planning.KIND_LABELS}
    )


@router.post("/plan/entries/{entry_id}/move")
def move_entry(request: Request, entry_id: int, day: str = Form(""), session: Session = Depends(get_session)):
    entry = planning.get_entry(session, entry_id)
    original_week = entry.week_start
    planning.move(session, entry_id, _parse_day(day))
    return week_response(request, session, original_week, close_sheet=True)


@router.post("/plan/entries/{entry_id}/delete")
def delete_entry(request: Request, entry_id: int, session: Session = Depends(get_session)):
    ws = planning.get_entry(session, entry_id).week_start
    planning.remove(session, entry_id)
    return week_response(request, session, ws, close_sheet=True)


@router.post("/plan/entries/{entry_id}/cooked")
def cooked(request: Request, entry_id: int, session: Session = Depends(get_session)):
    entry = planning.mark_cooked(session, entry_id, today())
    return week_response(request, session, entry.week_start, toast="Marked as cooked" if entry.cooked_on else None)


@router.post("/plan/to-list")
def to_list(request: Request, week: date | None = None, session: Session = Depends(get_session)):
    ws = _ws(week)
    n = planning.add_week_to_list(session, ws)
    msg = f"Added ingredients for {n} meal{'s' if n != 1 else ''}" if n else "Nothing new to add from the plan"
    if request.headers.get("HX-Target") == "list-body":
        return items_response(request, session, toast=msg)
    return week_response(request, session, ws, toast=msg)


@router.post("/plan/copy-last")
def copy_last(request: Request, week: date | None = None, session: Session = Depends(get_session)):
    ws = _ws(week)
    n = planning.copy_week(session, ws - timedelta(days=7), ws)
    if n is None:
        return week_response(request, session, ws, toast="This week already has meals")
    return week_response(request, session, ws, toast=f"Copied {n} entr{'ies' if n != 1 else 'y'} from last week")


@router.get("/meals/{meal_id}/plan")
def meal_plan_sheet(request: Request, meal_id: int, week: date | None = None, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    ws = _ws(week)
    return templates.TemplateResponse(
        request,
        "plan/_meal_sheet.html",
        {"meal": meal, "view": planning.week(session, ws), "this_week": planning.current_week(),
         "next_week": planning.current_week() + timedelta(days=7), "kind_labels": planning.KIND_LABELS},
    )


@router.get("/more/history")
def history(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "more/history.html", {"active": "more", "groups": planning.history(session)})
