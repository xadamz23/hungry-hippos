import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile

from app.db import get_session
from app.models import Meal, MealPhoto, Section
from app.services import meals as meal_svc
from app.services import planning, shopping
from app.services.planning import week_start
from app.templating import templates, today

router = APIRouter(prefix="/meals")


def get_meal(session: Session, meal_id: int) -> Meal:
    meal = session.get(Meal, meal_id)
    if meal is None:
        raise HTTPException(404, "That meal doesn't exist anymore.")
    return meal


INT_MAX = 2**31 - 1  # Postgres INTEGER


def _int_or_none(value) -> int | None:
    try:
        n = int(str(value).strip())
        return n if 0 < n <= INT_MAX else None
    except (TypeError, ValueError):
        return None


def _pick_label(pick: str | None) -> str:
    try:
        d = date.fromisoformat(pick or "")
    except ValueError:
        return "sometime this week"
    return f"{d:%A}, {d:%b} {d.day}"


def pick_short(pick: str | None) -> str:
    """What the pick buttons add to: "Tuesday", or "this week" for no day."""
    try:
        return f"{date.fromisoformat(pick or ''):%A}"
    except ValueError:
        return "this week"


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
        "pick_label": _pick_label(pick),
        "pick_short": pick_short(pick),
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


def _http_url(value) -> str:
    """Only keep http(s) links; anything else (javascript:, data:) becomes empty."""
    url = str(value or "").strip()
    return url if url.lower().startswith(("http://", "https://")) else ""


def _image_url(value) -> str:
    """A web link, or the address of a photo uploaded here (save_meal checks it's this meal's)."""
    url = str(value or "").strip()
    return url if meal_svc.photo_id_from_url(url) is not None else _http_url(url)


async def _read_photo(form) -> tuple[bytes, str] | str | None:
    """The uploaded photo as (data, content type), an error message, or None when no photo was sent."""
    upload = form.get("photo")
    if not isinstance(upload, UploadFile):
        return None
    data = await upload.read(meal_svc.PHOTO_MAX_BYTES + 1)
    if not data:
        return None
    if len(data) > meal_svc.PHOTO_MAX_BYTES:
        return "That photo is too big. Pick one under 10 MB."
    content_type = meal_svc.sniff_image(data)
    if content_type is None:
        return "That file isn't a photo we can use. Pick a JPEG, PNG or WebP."
    return data, content_type


def _form_kwargs(form) -> dict:
    # section_<i> overrides line i's section; when guess_<i> is sent too, only a changed value counts
    overrides = {}
    for key, value in form.items():
        if key.startswith("section_") and key[8:].isdigit() and str(value).isdigit():
            i = key[8:]
            if form.get(f"guess_{i}") != value:
                overrides[int(i)] = int(value)
    lines = form.getlist("ingredient_lines")
    if lines:
        # One field is one ingredient: fold its whitespace, including characters splitlines() would break on.
        # save_meal skips blank lines, so number the overrides by position among the non-blank ones.
        lines = [" ".join(str(x).split()) for x in lines]
        positions = {}
        for i, line in enumerate(lines):
            if line:
                positions[i] = len(positions)
        overrides = {positions[i]: sid for i, sid in overrides.items() if i in positions}
        ingredients = "\n".join(lines)
    else:
        ingredients = str(form.get("ingredients", ""))
    return dict(
        name=str(form.get("name", "")),
        ingredients_text=ingredients,
        steps_text=str(form.get("steps", "")),
        notes=str(form.get("notes", "")),
        tags=[t for t in str(form.get("tags", "")).split(",")],
        servings=_int_or_none(form.get("servings")),
        total_minutes=_int_or_none(form.get("total_minutes")),
        favorite=bool(form.get("favorite")),
        source_url=_http_url(form.get("source_url")) if "source_url" in form else None,
        image_url=_image_url(form.get("image_url")) if "image_url" in form else None,
        section_overrides=overrides,
    )


def _retry_values(form, kwargs, meal: Meal | None, photo) -> dict:
    # dict(form) keeps only the last of the repeated ingredient_lines, so put the joined lines back
    values = {**dict(form), "ingredients": kwargs["ingredients_text"]}
    if photo is not None:
        # A picked photo sends image_url empty, and the browser can't re-attach the file to the retry form.
        # Show the current picture again so saving the retry doesn't remove it.
        values["image_url"] = meal.image_url if meal and meal.image_url else ""
    return values


def _error(photo, kwargs) -> str | None:
    if not kwargs["name"].strip():
        error = "Give the meal a name."
        return error + " Your new photo wasn't saved, so add it again." if isinstance(photo, tuple) else error
    return photo if isinstance(photo, str) else None


def _form_page(request, session, meal=None, values=None, error=None, mode="manual"):
    return templates.TemplateResponse(
        request,
        "meals/form.html",
        {"active": "meals", "meal": meal, "v": values or {}, "error": error, "mode": mode,
         "tags": meal_svc.all_tags(session), "staples": shopping.all_staples(session)},
    )


@router.get("/new")
def new(request: Request, mode: str = "manual", session: Session = Depends(get_session)):
    return _form_page(request, session, mode="link" if mode == "link" else "manual")


@router.post("")
async def create(request: Request, session: Session = Depends(get_session)):
    form = await request.form()
    kwargs = _form_kwargs(form)
    photo = await _read_photo(form)
    if error := _error(photo, kwargs):
        return _form_page(request, session, values=_retry_values(form, kwargs, None, photo), error=error)
    meal = meal_svc.save_meal(session, meal=None, **kwargs)
    if isinstance(photo, tuple):
        meal_svc.set_photo(session, meal, *photo)
    return RedirectResponse(f"/meals/{meal.id}", status_code=303)


@router.get("/photos/{photo_id}")
def meal_photo(photo_id: int, session: Session = Depends(get_session)):
    photo = session.get(MealPhoto, photo_id)
    if photo is None:
        raise HTTPException(404, "That photo doesn't exist anymore.")
    # A photo never changes: replacing it makes a new one at a new address.
    return Response(photo.data, media_type=photo.content_type,
                    headers={"Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff"})


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
        "image_url": meal.image_url or "",
    }
    return _form_page(request, session, meal=meal, values=values)


@router.post("/{meal_id}")
async def update(request: Request, meal_id: int, session: Session = Depends(get_session)):
    meal = get_meal(session, meal_id)
    form = await request.form()
    kwargs = _form_kwargs(form)
    photo = await _read_photo(form)
    if error := _error(photo, kwargs):
        return _form_page(request, session, meal=meal, values=_retry_values(form, kwargs, meal, photo), error=error)
    meal_svc.save_meal(session, meal=meal, **kwargs)
    if isinstance(photo, tuple):
        meal_svc.set_photo(session, meal, *photo)
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


@router.post("/{meal_id}/finish")
def finish_cooking(request: Request, meal_id: int, session: Session = Depends(get_session)):
    """Finish in cook mode: log the meal as cooked today and go back to it, with an Undo in case it was a read-through."""
    meal = get_meal(session, meal_id)
    log = planning.finish_cooking(session, meal.id, today())
    url = f"/meals/{meal.id}"
    if not request.headers.get("HX-Request"):
        return RedirectResponse(url, status_code=303)
    response = detail(request, meal.id, session)
    response.headers["HX-Push-Url"] = url
    toast = {"message": f"Marked {meal.name} as cooked", "undo": f"/meals/cook-log/{log.id}/undo"} if log else "Already marked as cooked today"
    response.headers["HX-Trigger-After-Settle"] = json.dumps({"toast": toast})
    return response


@router.post("/cook-log/{log_id}/undo")
def undo_cooked(log_id: int, session: Session = Depends(get_session)):
    planning.undo_cooked(session, log_id)
    return Response(status_code=204, headers={"HX-Refresh": "true"})


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
