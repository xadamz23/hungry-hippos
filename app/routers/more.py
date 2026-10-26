import json
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.clock import today
from app.config import get_settings
from app.db import get_session
from app.models import ItemSectionMap, ListItem, Section, Staple
from app.services import importer
from app.services.ingredients import parse_line
from app.services.sections import guess_section
from app.templating import templates

router = APIRouter(prefix="/more")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


def last_backup(directory: Path) -> datetime | None:
    try:
        files = list(Path(directory).glob("*.sql.gz"))
    except OSError:
        return None
    if not files:
        return None
    newest = max(f.stat().st_mtime for f in files)
    return datetime.fromtimestamp(newest).astimezone()


def backup_label() -> str:
    when = last_backup(Path(get_settings().backup_dir))
    if when is None:
        return "No backups yet"
    local = when.astimezone(ZoneInfo(get_settings().tz))
    days = (today() - local.date()).days
    day = "today" if days == 0 else "yesterday" if days == 1 else f"{local:%b} {local.day}"
    return f"Last one {local:%-I:%M %p} {day}"


@router.get("")
def more(request: Request, session: Session = Depends(get_session)):
    ctx = {
        "active": "more",
        "section_count": session.scalar(select(func.count()).select_from(Section)),
        "staple_count": session.scalar(select(func.count()).select_from(Staple)),
        "remembered_count": session.scalar(select(func.count()).select_from(ItemSectionMap)),
        "checked_count": session.scalar(select(func.count()).select_from(ListItem).where(ListItem.checked.is_(True))),
        "ai": importer.ai_enabled(),
        "backup": backup_label(),
    }
    return templates.TemplateResponse(request, "more/index.html", ctx)


# ---------- sections ----------

def _sections(session: Session) -> list[Section]:
    return session.scalars(select(Section).order_by(Section.position, Section.id)).all()


@router.get("/sections")
def sections_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "more/sections.html", {"active": "more", "sections": _sections(session)})


@router.post("/sections/order")
def order_sections(ids: list[int] = Form(...), session: Session = Depends(get_session)):
    by_id = {s.id: s for s in _sections(session)}
    for pos, sid in enumerate(i for i in ids if i in by_id):
        by_id[sid].position = pos
    session.commit()
    return Response(status_code=204)


@router.post("/sections")
def add_section(request: Request, name: str = Form(""), session: Session = Depends(get_session)):
    name = name.strip()[:80]
    exists = session.scalar(select(Section).where(func.lower(Section.name) == name.lower()))
    if name and exists is None:
        position = session.scalar(select(func.coalesce(func.max(Section.position), -1))) + 1
        session.add(Section(name=name, color="#6B7A72", position=position))
        session.commit()
    return templates.TemplateResponse(request, "more/_section_rows.html", {"sections": _sections(session)})


@router.post("/sections/{section_id}")
def edit_section(section_id: int, name: str = Form(""), color: str = Form(""), session: Session = Depends(get_session)):
    section = session.get(Section, section_id)
    if section is not None:
        name = name.strip()[:80]
        clash = session.scalar(select(Section).where(func.lower(Section.name) == name.lower(), Section.id != section_id))
        if name and clash is None:
            section.name = name
        if HEX.match(color):
            section.color = color.upper()
        session.commit()
    return Response(status_code=204, headers={"HX-Trigger": json.dumps({"toast": "Saved"})})


# ---------- staples ----------

def _staples(session: Session) -> list[Staple]:
    return session.scalars(
        select(Staple).options(selectinload(Staple.section)).order_by(Staple.position, Staple.id)
    ).all()


@router.get("/staples")
def staples_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "more/staples.html", {"active": "more", "staples": _staples(session)})


@router.post("/staples")
def add_staple(request: Request, text: str = Form(""), session: Session = Depends(get_session)):
    parsed = parse_line(text)
    name = parsed.name or parsed.raw
    if name:
        position = session.scalar(select(func.coalesce(func.max(Staple.position), -1))) + 1
        session.add(
            Staple(
                name=name, name_key=parsed.name_key or name.lower(), position=position,
                amounts=[{"qty": parsed.qty, "unit": parsed.unit}] if parsed.qty is not None else [],
                section_id=guess_section(session, parsed.name_key).id,
            )
        )
        session.commit()
    return templates.TemplateResponse(request, "more/_staple_rows.html", {"staples": _staples(session)})


@router.post("/staples/order")
def order_staples(ids: list[int] = Form(...), session: Session = Depends(get_session)):
    by_id = {s.id: s for s in _staples(session)}
    for pos, sid in enumerate(i for i in ids if i in by_id):
        by_id[sid].position = pos
    session.commit()
    return Response(status_code=204)


@router.post("/staples/{staple_id}/delete")
def delete_staple(request: Request, staple_id: int, session: Session = Depends(get_session)):
    staple = session.get(Staple, staple_id)
    if staple is not None:
        session.delete(staple)
        session.commit()
    return templates.TemplateResponse(request, "more/_staple_rows.html", {"staples": _staples(session)})


# ---------- remembered sections ----------

def _remembered(session: Session) -> list[ItemSectionMap]:
    return session.scalars(
        select(ItemSectionMap).options(selectinload(ItemSectionMap.section)).order_by(ItemSectionMap.name_key)
    ).all()


@router.get("/remembered")
def remembered_page(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(request, "more/remembered.html", {"active": "more", "rows": _remembered(session)})


@router.post("/remembered/delete")
def delete_remembered(request: Request, key: str = Form(...), session: Session = Depends(get_session)):
    row = session.get(ItemSectionMap, key)
    if row is not None:
        session.delete(row)
        session.commit()
    return templates.TemplateResponse(request, "more/_remembered_rows.html", {"rows": _remembered(session)})
