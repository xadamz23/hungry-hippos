import json

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Section
from app.services import shopping
from app.templating import templates

router = APIRouter(prefix="/list")


def list_context(session: Session) -> dict:
    left, total = shopping.progress(session)
    return {
        "groups": shopping.grouped(session),
        "left": left,
        "total": total,
        "staples": shopping.available_staples(session),
    }


def items_response(request: Request, session: Session, *, toast: str | None = None, close_sheet: bool = False):
    response = templates.TemplateResponse(request, "list/_items.html", list_context(session))
    triggers = {}
    if toast:
        triggers["toast"] = toast
    if close_sheet:
        triggers["close-sheet"] = True
    if triggers:
        response.headers["HX-Trigger"] = json.dumps(triggers)
    return response


@router.get("")
def list_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "list/page.html", {"active": "list", **list_context(session)})


@router.get("/items")
def list_items(request: Request, session: Session = Depends(get_session)):
    return items_response(request, session)


@router.post("/add")
def add(request: Request, text: str = Form(""), session: Session = Depends(get_session)):
    if text.strip():
        shopping.add_text(session, text)
    return items_response(request, session)


@router.post("/staple/{staple_id}")
def add_staple(request: Request, staple_id: int, session: Session = Depends(get_session)):
    shopping.add_staple(session, staple_id)
    return items_response(request, session)


@router.post("/clear-checked")
def clear_checked(request: Request, session: Session = Depends(get_session)):
    n = shopping.clear_checked(session)
    return items_response(request, session, toast=f"Cleared {n} checked item{'s' if n != 1 else ''}")


@router.post("/clear-all")
def clear_all(request: Request, session: Session = Depends(get_session)):
    shopping.clear_all(session)
    return items_response(request, session, toast="Cleared the list")


@router.post("/{item_id}/toggle")
def toggle(request: Request, item_id: int, session: Session = Depends(get_session)):
    shopping.toggle(session, item_id)
    return items_response(request, session)


@router.get("/{item_id}/edit")
def edit_sheet(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = shopping.get_item(session, item_id)
    sections = session.scalars(select(Section).order_by(Section.position)).all()
    return templates.TemplateResponse(request, "list/_item_sheet.html", {"item": item, "sections": sections})


@router.post("/{item_id}")
def save(
    request: Request,
    item_id: int,
    amount: str = Form(""),
    section_id: int = Form(...),
    remember: str | None = Form(None),
    session: Session = Depends(get_session),
):
    shopping.update(session, item_id, amount, section_id, remember=bool(remember))
    return items_response(request, session, close_sheet=True)


@router.post("/{item_id}/delete")
def delete(request: Request, item_id: int, session: Session = Depends(get_session)):
    item = shopping.get_item(session, item_id)
    name = item.name
    shopping.remove(session, item_id)
    return items_response(request, session, toast=f"Removed {name}", close_sheet=True)

