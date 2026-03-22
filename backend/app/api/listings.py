from fastapi import APIRouter, Depends, Query
from sqlalchemy import asc
from sqlalchemy.orm import Session

from backend.app.database import get_session
from backend.app.models import Listing
from backend.app.schemas import ListingOut

router = APIRouter()


@router.get("/listings", response_model=list[ListingOut])
def get_listings(
    region: str | None = Query(None),
    city: str | None = Query(None),
    postal_code: str | None = Query(None),
    listing_type: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
):
    q = session.query(Listing)

    if region:
        q = q.filter(Listing.region == region.upper())
    if city:
        q = q.filter(Listing.city == city.lower())
    if postal_code:
        q = q.filter(Listing.postal_code == postal_code)
    if listing_type:
        q = q.filter(Listing.listing_type == listing_type.lower())

    q = q.order_by(asc(Listing.price_per_sqft).nulls_last())
    q = q.offset(offset).limit(limit)

    return q.all()
