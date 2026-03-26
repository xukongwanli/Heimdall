"""add discovered_sites and extraction_selectors tables

Revision ID: f62d7ad90773
Revises: ec4dc1a90413
Create Date: 2026-03-26 02:39:12.298803

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f62d7ad90773'
down_revision: Union[str, None] = 'ec4dc1a90413'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table('discovered_sites',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('root_url', sa.Text(), nullable=False),
    sa.Column('domain', sa.Text(), nullable=False),
    sa.Column('discovery_query', sa.Text(), nullable=True),
    sa.Column('llm_classification', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('max_crawl_rate', sa.Numeric(), nullable=True),
    sa.Column('extraction_method', sa.String(length=20), nullable=True),
    sa.Column('status', sa.String(length=20), server_default='approved', nullable=False),
    sa.Column('last_probed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('last_extracted_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('root_url')
    )
    op.create_index('ix_discovered_sites_domain', 'discovered_sites', ['domain'], unique=False)
    op.create_index('ix_discovered_sites_status', 'discovered_sites', ['status'], unique=False)
    op.create_table('extraction_selectors',
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('site_id', sa.UUID(), nullable=False),
    sa.Column('page_pattern', sa.Text(), nullable=False),
    sa.Column('selectors', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('structured_data_type', sa.String(length=20), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('validated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['site_id'], ['discovered_sites.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_extraction_selectors_site_id', 'extraction_selectors', ['site_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_extraction_selectors_site_id', table_name='extraction_selectors')
    op.drop_table('extraction_selectors')
    op.drop_index('ix_discovered_sites_status', table_name='discovered_sites')
    op.drop_index('ix_discovered_sites_domain', table_name='discovered_sites')
    op.drop_table('discovered_sites')
