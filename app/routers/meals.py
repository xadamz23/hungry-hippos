import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Meal, Section
from app.services import meals as meal_svc
from app.services import shopping
from app.services.planning import week_start
from app.templating import templates, today

router = APIRouter(prefix="/meals")


def get_meal(session: Session, meal_id: int) -> Meal:
    meal = session.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(404, "That meal doesn't exist anymore.")
    return meal


def _int_or_none(value) -> int | None:
    try:
        n = int(str(value).strip())
        return n if n > 0 else None
    except (TypeError, ValueError):
        return None


def list_context(session: Session, q=None, fav=False, tag=None, pick=None, week=None, selected=None) -> dict:
    ws = week or week_start(today())
    return {
        "rows": meal_svc.search(session, q=q, favorites=fav, tag=tag, pick_mode=pick is not None, week_start=ws),
        "tags": meal_svc.all_tags(session),
        "q": q or "",
        "fav": fav,
        "tag": tag,
        "pick": pick,
        "week": ws,
        "selected": selected,
        "filtered": bool(q or fav or tag),
    }


@router.get("")
def index(
    request: Request,
    q: str | None = None,
    fav: bool = False,
    tag: str | None = None,
    pick: str | None = None,
    week: date | None = None,
    session: Session = Depends(get_session),
):
    ctx = list_context(session, q, fav, tag, pick, week)
    if request.headers.get("HX-Target") == "meal-rows":
        return templates.TemplateResponse(request, "meals/_rows.html", ctx)
    return templates.TemplateResponse(request, "meals/index.html", {"active": "meals", **ctx})


def _form_kwargs(form) -> dict:
    # section_<i> overrides line i's section; when guess_<i> is sent too, only a changed value counts
    overrides = {}
    for key, value in form.items():
        if key.startswith("section_") and key[8:].isdigit() and str(value).isdigit():
            i = key[8:]
            if form.get(f"guess_{i}") != value:
                overrides[int(i)] = int(value)
    lines = form.getlist("ingredient_lines")
    ingredients = "\n".join(str(x) for x in lines) if lines else str(form.get("ingredients", ""))
    return dict(
        name=str(form.get("name", "")),
        ingredients_text=ingredients,
        steps_text=str(form.get("steps", "")),
        notes=str(form.get("notes", "")),
        tags=[t for t in str(form.get("tags", "")).split(",")],
        servings=_int_or_none(form.get("servings")),
        total_minutes=_int_or_none(form.get("total_minutes")),
        favorite=bool(form.get("favorite")),
        source_url=str(form.get("source_url", "")) if "source_url" in form else None,
        image_url=str(form.get("image_url", "")) if "image_url" in form else None,
        section_overrides=overrides,
    )


def _form_page(request, session, meal=None, values=None, error=None, mode="manual"):
    return templates.TemplateResponse(
        request,
        "meals/form.html",
        {"active": "meals", "meal": meal, "v": values or {}, "error": error, "mode": mode,
         "tags": meal_svc.all_tags(session)},
    )


@router.get("/new")
def new(request: Request, mode: str = "manual", session: Session = Depends(get_session)):
    return _form_page(request, session, mode="link" if mode == "link" else "manual")


@router.post("")
async def create(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    kwargs = _form_kwargs(form)
    if not kwargs["name"].strip():
        return _form_page(request, session, values=dict(form), error="Give the meal a name.")
    meal = meal_svc.save_meal(session, meal=None, **kwargs)
    return RedirectResponse(f"/meals/{meal.id}", status_code=303)


@router.get("/{meal_id}")
def detail(request: Request, meal_id: int, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    last_made, times_made = meal_svc.stats_for(session, meal.id)
    sections = {s.id: s for s in session.scalars(select(Section))}
    return templates.TemplateResponse(
        request,
        "meals/detail.html",
        {"active": "meals", "meal": meal, "last_made": last_made, "times_made": times_made,
         "sections": sections, **list_context(session, selected=meal.id)},
    )


@router.get("/{meal_id}/edit")
def edit(request: Request, meal_id: int, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    values = {
        "name": meal.name,
        "ingredients": "\n".join(i.raw for i in meal.ingredients),
        "steps": meal.steps,
        "notes": meal.notes,
        "tags": ", ".join(t.name for t in meal.tags),
        "servings": meal.servings or "",
        "total_minutes": meal.total_minutes or "",
        "favorite": meal.favorite,
    }
    return _form_page(request, session, meal=meal, values=values)


@router.post("/{meal_id}")
async def update(request: Request, meal_id: int, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    form = await request.form()
    kwargs = _form_kwargs(form)
    if not kwargs["name"].strip():
        return _form_page(request, session, meal=meal, values=dict(form), error="Give the meal a name.")
    meal_svc.save_meal(session, meal=meal, **kwargs)
    return RedirectResponse(f"/meals/{meal.id}", status_code=303)


@router.post("/{meal_id}/delete")
def delete(meal_id: int, session: Session = Depends(get_session)):
    session.delete(get_meal(session, meal_id))
    session.commit()
    return RedirectResponse("/meals", status_code=303)


@router.post("/{meal_id}/favorite")
def favorite(request: Request, meal_id: int, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    meal.favorite = not meal.favorite
    session.commit()
    return templates.TemplateResponse(request, "meals/_star.html", {"meal": meal})


@router.post("/{meal_id}/to-list")
def to_list(meal_id: int, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    n = shopping.add_meal(session, meal)
    msg = f"Added {n} item{'s' if n != 1 else ''} to the list" if n else "This meal has no ingredients yet"
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": msg})})


@router.get("/{meal_id}/cook")
def cook(request: Request, meal_id: int, servings: int | None = None, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    base = meal.servings or 4
    servings = max(1, min(servings or base, 99))
    factor = servings / base
    steps = [{"text": s, "uses": meal_svc.ingredients_for_step(meal, s, factor)} for s in meal.step_list]
    scaled = [(ing.name, meal_svc.fmt(meal_svc.scale(ing.amounts, factor))) for ing in meal.ingredients]
    return templates.TemplateResponse(
        request,
        "meals/cook.html",
        {"meal": meal, "servings": servings, "base": base, "steps": steps, "scaled": scaled, "bare": True},
    )
