from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ListingOut(BaseModel):
    id: UUID
    source: str
    listing_type: str
    address: str
    city: str
    country: str
    region: str
    postal_code: str
    price: Decimal
    sqft: Decimal | None
    price_per_sqft: Decimal | None
    source_url: str
    published_at: datetime
    crawled_at: datetime

    model_config = {"from_attributes": True}


class MetricPoint(BaseModel):
    level: str
    code: str
    name: str
    lat: float | None
    lng: float | None
    value: float | None
    region: str
    listing_count: int


class SearchResult(BaseModel):
    city: str | None
    region: str
    avg_buy_price_per_sqft: float | None
    avg_rent_per_sqft: float | None
    rent_to_price_ratio: float | None
    listing_count: int
