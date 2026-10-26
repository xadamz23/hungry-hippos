from sqlalchemy import select

from app.models import Section, Staple
from app.seed import ensure_seed


def test_seed_creates_sections_in_walk_order(session):
    ensure_seed(session)
    sections = session.scalars(select(Section).order_by(Section.position)).all()
    assert len(sections) == 14
    assert [s.position for s in sections] == list(range(14))
    assert sections[0].name == "Produce"
    assert sections[-1].name == "Other"
    assert len({s.color for s in sections}) == 14


def test_seed_is_idempotent(session):
    ensure_seed(session)
    ensure_seed(session)
    assert len(session.scalars(select(Section)).all()) == 14
    assert len(session.scalars(select(Staple)).all()) == 4
