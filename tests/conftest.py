import os

import psycopg
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

TEST_DB = "hungry_hippos_test"
_base = make_url(os.environ.get("DATABASE_URL", "postgresql+psycopg://hh:hh@127.0.0.1:5433/hungry_hippos"))
TEST_URL = _base.set(database=TEST_DB)
os.environ["DATABASE_URL"] = TEST_URL.render_as_string(hide_password=False)
os.environ.setdefault("ANTHROPIC_API_KEY", "")


def _ensure_db() -> None:
    admin = _base.set(drivername="postgresql", database="postgres").render_as_string(hide_password=False)
    with psycopg.connect(admin, autocommit=True) as conn:
        if not conn.execute("SELECT 1 FROM pg_database WHERE datname=%s", (TEST_DB,)).fetchone():
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


_ensure_db()

from app import models  # noqa: E402,F401
from app.db import Base  # noqa: E402

engine = create_engine(TEST_URL)
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)
TestSession = sessionmaker(bind=engine, expire_on_commit=False)


@pytest.fixture
def session():
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
    with TestSession() as s:
        yield s


@pytest.fixture
def seeded(session):
    from app.seed import ensure_seed

    ensure_seed(session)
    return session


@pytest.fixture
def client(seeded):
    from fastapi.testclient import TestClient

    from app.db import get_session
    from app.main import app

    def _override():
        yield seeded

    app.dependency_overrides[get_session] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()
