"""add geo_reference and region_metrics, drop zip_metrics

Revision ID: ec4dc1a90413
Revises: 27d1dff153fa
Create Date: 2026-03-25 00:03:21.480251

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = 'ec4dc1a90413'
down_revision: Union[str, None] = '27d1dff153fa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Create geo_reference table
    op.create_table('geo_reference',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('level', sa.String(length=10), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('state_code', sa.String(length=2), nullable=True),
        sa.Column('state_fips', sa.String(length=2), nullable=True),
        sa.Column('county_fips', sa.String(length=5), nullable=True),
        sa.Column('county_name', sa.Text(), nullable=True),
        sa.Column('city', sa.Text(), nullable=True),
        sa.Column('postal_code', sa.Text(), nullable=True),
        sa.Column('lat', sa.Numeric(), nullable=True),
        sa.Column('lng', sa.Numeric(), nullable=True),
        sa.Column('geog', geoalchemy2.types.Geography(geometry_type='POINT', srid=4326, from_text='ST_GeogFromText', name='geography'), nullable=True),
        sa.Column('land_area_sqft', sa.Numeric(), nullable=True),
        sa.Column('water_area_sqft', sa.Numeric(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('level', 'code', name='uq_geo_ref_level_code'),
    )
    op.create_index('ix_geo_ref_level_state', 'geo_reference', ['level', 'state_code'], unique=False)
    op.create_index('ix_geo_ref_level_city_state', 'geo_reference', ['level', 'city', 'state_code'], unique=False)
    op.create_index('ix_geo_ref_geog', 'geo_reference', ['geog'], unique=False, postgresql_using='gist')

    # Create region_metrics table
    op.create_table('region_metrics',
        sa.Column('level', sa.String(length=10), nullable=False),
        sa.Column('code', sa.Text(), nullable=False),
        sa.Column('name', sa.Text(), nullable=False),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('region', sa.Text(), nullable=False),
        sa.Column('lat', sa.Numeric(), nullable=True),
        sa.Column('lng', sa.Numeric(), nullable=True),
        sa.Column('avg_buy_price_per_sqft', sa.Numeric(), nullable=True),
        sa.Column('avg_rent_per_sqft', sa.Numeric(), nullable=True),
        sa.Column('rent_to_price_ratio', sa.Numeric(), nullable=True),
        sa.Column('listing_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('level', 'code'),
    )

    # Add county columns to listings
    op.add_column('listings', sa.Column('county_fips', sa.String(length=5), nullable=True))
    op.add_column('listings', sa.Column('county_name', sa.Text(), nullable=True))
    op.create_index('ix_listings_county_fips', 'listings', ['county_fips'], unique=False)

    # Drop zip_metrics table
    op.drop_table('zip_metrics')


def downgrade() -> None:
    """Downgrade schema."""
    # Recreate zip_metrics
    op.create_table('zip_metrics',
        sa.Column('postal_code', sa.Text(), nullable=False),
        sa.Column('country', sa.String(length=2), nullable=False),
        sa.Column('region', sa.Text(), nullable=False),
        sa.Column('lat', sa.Numeric(), nullable=True),
        sa.Column('lng', sa.Numeric(), nullable=True),
        sa.Column('avg_buy_price_per_sqft', sa.Numeric(), nullable=True),
        sa.Column('avg_rent_per_sqft', sa.Numeric(), nullable=True),
        sa.Column('rent_to_price_ratio', sa.Numeric(), nullable=True),
        sa.Column('listing_count', sa.Integer(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('postal_code'),
    )

    # Remove county columns from listings
    op.drop_index('ix_listings_county_fips', table_name='listings')
    op.drop_column('listings', 'county_name')
    op.drop_column('listings', 'county_fips')

    # Drop new tables
    op.drop_index('ix_geo_ref_geog', table_name='geo_reference', postgresql_using='gist')
    op.drop_index('ix_geo_ref_level_city_state', table_name='geo_reference')
    op.drop_index('ix_geo_ref_level_state', table_name='geo_reference')
    op.drop_table('geo_reference')
    op.drop_table('region_metrics')
