import uuid

from geoalchemy2 import Geometry
from sqlalchemy import (
    Column, DateTime, Index, Numeric, String, Text, UniqueConstraint, Integer
)
from sqlalchemy.dialects.postgresql import UUID

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

    __table_args__ = (
        UniqueConstraint("source", "address", "listing_type", name="uq_source_address_type"),
        Index("ix_listings_country", "country"),
        Index("ix_listings_region", "region"),
        Index("ix_listings_city", "city"),
        Index("ix_listings_postal_code", "postal_code"),
        Index("ix_listings_listing_type", "listing_type"),
        Index("ix_listings_coordinates", "coordinates", postgresql_using="gist"),
    )


class ZipMetrics(Base):
    __tablename__ = "zip_metrics"

    postal_code = Column(Text, primary_key=True)
    country = Column(String(2), nullable=False, default="US")
    region = Column(Text, nullable=False)
    lat = Column(Numeric, nullable=True)
    lng = Column(Numeric, nullable=True)
    avg_buy_price_per_sqft = Column(Numeric, nullable=True)
    avg_rent_per_sqft = Column(Numeric, nullable=True)
    rent_to_price_ratio = Column(Numeric, nullable=True)
    listing_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False)
