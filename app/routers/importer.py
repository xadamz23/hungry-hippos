from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import Section
from app.services import importer, meals as meal_svc
from app.services.ingredients import parse_line
from app.services.sections import OTHER, guess_section, staple_index
from app.templating import templates

router = APIRouter()


@router.post("/meals/import")
def import_recipe(request: Request, url: str = Form(""), session: Session = Depends(get_session)):
    try:
        recipe = importer.import_url(url)
    except importer.RecipeImportError as e:
        return templates.TemplateResponse(
            request, "meals/form.html",
            {"active": "meals", "meal": None, "v": {"url": url}, "error": str(e), "mode": "link",
             "tags": meal_svc.all_tags(session)},
        )
    lines = []
    staples = staple_index(session)
    for raw in recipe.ingredients:
        parsed = parse_line(raw)
        section = guess_section(session, parsed.name_key, staples)
        lines.append({"raw": raw, "parsed": parsed, "section": section, "unsure": section.name == OTHER})
    sections = session.scalars(select(Section).order_by(Section.position)).all()
    return templates.TemplateResponse(
        request, "meals/import_review.html",
        {"active": "meals", "recipe": recipe, "lines": lines, "sections": sections,
         "ai": importer.ai_enabled(), "tags": meal_svc.all_tags(session)},
    )
