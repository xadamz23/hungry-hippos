"""meal photos

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-29 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = '0005'
down_revision: Union[str, Sequence[str], None] = '0004'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'meal_photos',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('meal_id', sa.Integer(), nullable=False),
        sa.Column('content_type', sa.String(length=40), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['meal_id'], ['meals.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_meal_photos_meal_id'), 'meal_photos', ['meal_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_meal_photos_meal_id'), table_name='meal_photos')
    op.drop_table('meal_photos')
