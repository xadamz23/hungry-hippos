"""darker section colors so headers can use white text

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-29 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0004'
down_revision: Union[str, Sequence[str], None] = '0003'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (name, old color, new color). Only sections still on the old default change.
COLORS = [
    ("Frozen", "#4FC3F7", "#0E7490"),
    ("Bread & Condiments", "#F9A825", "#8D6E00"),
    ("Yogurt, Butter & Ritz", "#FF8A65", "#DB2777"),
    ("Health & Personal Care", "#7CB342", "#4D7C0F"),
]

UPDATE = sa.text("UPDATE sections SET color = :new WHERE name = :name AND color = :old")


def upgrade() -> None:
    """Upgrade schema."""
    for name, old, new in COLORS:
        op.execute(UPDATE.bindparams(name=name, old=old, new=new))


def downgrade() -> None:
    """Downgrade schema."""
    for name, old, new in COLORS:
        op.execute(UPDATE.bindparams(name=name, old=new, new=old))
