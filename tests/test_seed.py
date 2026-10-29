from sqlalchemy import select

from app.models import Section, Staple
from app.seed import DEFAULT_SECTIONS, ensure_seed
from app.services.sections import text_color


def test_seed_creates_sections_in_walk_order(session):
    ensure_seed(session)
    sections = session.scalars(select(Section).order_by(Section.position)).all()
    assert len(sections) == 19
    assert [s.position for s in sections] == list(range(19))
    assert sections[0].name == "Produce"
    assert sections[-1].name == "Other"
    assert len({s.color for s in sections}) == 19


def test_seed_is_idempotent(session):
    ensure_seed(session)
    ensure_seed(session)
    assert len(session.scalars(select(Section)).all()) == 19
    assert len(session.scalars(select(Staple)).all()) == 4


def test_default_sections_use_white_text():
    assert [name for name, color in DEFAULT_SECTIONS if text_color(color) != "#fff"] == []
