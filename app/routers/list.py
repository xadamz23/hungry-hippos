from fastapi import APIRouter, Request

from app.templating import templates

router = APIRouter()


@router.get("/list")
def list_page(request: Request):
    return templates.TemplateResponse(request, "list/page.html", {"active": "list"})
