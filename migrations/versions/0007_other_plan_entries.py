"""other plan entries: a typed meal name for meals not on the meal list

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0007'
down_revision: Union[str, Sequence[str], None] = '0006'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column('plan_entries', sa.Column('title', sa.String(length=80), nullable=True))
    op.add_column('cook_log', sa.Column('title', sa.String(length=80), nullable=True))
    op.alter_column('cook_log', 'meal_id', existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    """Downgrade schema. Drops the history and plan entries that have no meal."""
    op.execute("DELETE FROM cook_log WHERE meal_id IS NULL")
    op.execute("DELETE FROM plan_entries WHERE kind = 'other'")
    op.alter_column('cook_log', 'meal_id', existing_type=sa.Integer(), nullable=False)
    op.drop_column('cook_log', 'title')
    op.drop_column('plan_entries', 'title')
