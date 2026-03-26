import uuid

from geoalchemy2 import Geography, Geometry
from sqlalchemy import (
    Column, DateTime, ForeignKey, Index, Numeric, String, Text,
    UniqueConstraint, Integer,
)
from sqlalchemy.dialects.postgresql import UUID, JSONB

from backend.app.database import Base


class Listing(Base):
    __tablename__ = "listings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source = Column(String(20), nullable=False)  # zillow, realtor, redfin
    listing_type = Column(String(10), nullable=False)  # buy, rent
    address = Column(Text, nullable=False)
    city = Column(Text, nullable=False)
    country = Column(String(2), nullable=False, default="US")
    region = Column(Text, nullable=False)
    postal_code = Column(Text, nullable=False)
    price = Column(Numeric, nullable=False)
    sqft = Column(Numeric, nullable=True)
    price_per_sqft = Column(Numeric, nullable=True)
    coordinates = Column(Geometry("POINT", srid=4326), nullable=True)
    source_url = Column(Text, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=False)
    crawled_at = Column(DateTime(timezone=True), nullable=False)
    county_fips = Column(String(5), nullable=True)
    county_name = Column(Text, nullable=True)

    __table_args__ = (
        UniqueConstraint("source", "address", "listing_type", name="uq_source_address_type"),
        Index("ix_listings_country", "country"),
        Index("ix_listings_region", "region"),
        Index("ix_listings_city", "city"),
        Index("ix_listings_postal_code", "postal_code"),
        Index("ix_listings_listing_type", "listing_type"),
        Index("ix_listings_coordinates", "coordinates", postgresql_using="gist"),
        Index("ix_listings_county_fips", "county_fips"),
    )


class GeoReference(Base):
    __tablename__ = "geo_reference"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), nullable=False)       # state, county, city, zip
    code = Column(Text, nullable=False)               # TX, 48453, austin-tx, 78701
    name = Column(Text, nullable=False)
    state_code = Column(String(2), nullable=True)
    state_fips = Column(String(2), nullable=True)
    county_fips = Column(String(5), nullable=True)
    county_name = Column(Text, nullable=True)
    city = Column(Text, nullable=True)
    postal_code = Column(Text, nullable=True)
    lat = Column(Numeric, nullable=True)
    lng = Column(Numeric, nullable=True)
    geog = Column(Geography("POINT", srid=4326), nullable=True)
    land_area_sqft = Column(Numeric, nullable=True)
    water_area_sqft = Column(Numeric, nullable=True)

    __table_args__ = (
        UniqueConstraint("level", "code", name="uq_geo_ref_level_code"),
        Index("ix_geo_ref_level_state", "level", "state_code"),
        Index("ix_geo_ref_level_city_state", "level", "city", "state_code"),
        Index("ix_geo_ref_geog", "geog", postgresql_using="gist"),
    )


class RegionMetrics(Base):
    __tablename__ = "region_metrics"

    level = Column(String(10), nullable=False, primary_key=True)
    code = Column(Text, nullable=False, primary_key=True)
    name = Column(Text, nullable=False)
    country = Column(String(2), nullable=False, server_default="US")
    region = Column(Text, nullable=False)
    lat = Column(Numeric, nullable=True)
    lng = Column(Numeric, nullable=True)
    avg_buy_price_per_sqft = Column(Numeric, nullable=True)
    avg_rent_per_sqft = Column(Numeric, nullable=True)
    rent_to_price_ratio = Column(Numeric, nullable=True)
    listing_count = Column(Integer, nullable=False, server_default="0")
    updated_at = Column(DateTime(timezone=True), nullable=False)


class DiscoveredSite(Base):
    __tablename__ = "discovered_sites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    root_url = Column(Text, nullable=False, unique=True)
    domain = Column(Text, nullable=False)
    discovery_query = Column(Text, nullable=True)
    llm_classification = Column(JSONB, nullable=True)
    max_crawl_rate = Column(Numeric, nullable=True)
    extraction_method = Column(String(20), nullable=True)  # 'structured' or 'llm'
    status = Column(String(20), nullable=False, server_default="approved")
    last_probed_at = Column(DateTime(timezone=True), nullable=True)
    last_extracted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_discovered_sites_domain", "domain"),
        Index("ix_discovered_sites_status", "status"),
    )


class ExtractionSelector(Base):
    __tablename__ = "extraction_selectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), ForeignKey("discovered_sites.id", ondelete="CASCADE"), nullable=False)
    page_pattern = Column(Text, nullable=False)
    selectors = Column(JSONB, nullable=True)
    structured_data_type = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    validated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint("site_id", "page_pattern", name="uq_selector_site_pattern"),
        Index("ix_extraction_selectors_site_id", "site_id"),
    )
