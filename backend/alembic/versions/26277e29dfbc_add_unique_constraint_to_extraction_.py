"""add unique constraint to extraction_selectors

Revision ID: 26277e29dfbc
Revises: f62d7ad90773
Create Date: 2026-03-26 03:00:51.763859

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '26277e29dfbc'
down_revision: Union[str, None] = 'f62d7ad90773'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_unique_constraint(
        'uq_selector_site_pattern',
        'extraction_selectors',
        ['site_id', 'page_pattern'],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint(
        'uq_selector_site_pattern',
        'extraction_selectors',
        type_='unique',
    )
