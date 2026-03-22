from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, case
from sqlalchemy.orm import Session

from backend.app.database import get_session
from backend.app.models import Listing
from backend.app.schemas import SearchResult

router = APIRouter()


@router.get("/search", response_model=list[SearchResult])
def search_listings(
    q: str = Query(..., min_length=1),
    session: Session = Depends(get_session),
):
    search_term = q.strip().lower()

    avg_buy = func.avg(
        case(
            (
                (Listing.listing_type == "buy") & (Listing.price_per_sqft.isnot(None)),
                Listing.price_per_sqft,
            )
        )
    )
    avg_rent = func.avg(
        case(
            (
                (Listing.listing_type == "rent") & (Listing.price_per_sqft.isnot(None)),
                Listing.price_per_sqft,
            )
        )
    )

    query = (
        session.query(
            Listing.city,
            Listing.region,
            avg_buy.label("avg_buy_price_per_sqft"),
            avg_rent.label("avg_rent_per_sqft"),
            func.count().label("listing_count"),
        )
        .filter(
            func.lower(Listing.city).contains(search_term)
            | func.lower(Listing.region).contains(search_term)
        )
        .group_by(Listing.city, Listing.region)
        .order_by(func.count().desc())
        .limit(20)
    )

    rows = query.all()
    results = []
    for r in rows:
        buy = float(r.avg_buy_price_per_sqft) if r.avg_buy_price_per_sqft else None
        rent = float(r.avg_rent_per_sqft) if r.avg_rent_per_sqft else None
        ratio = None
        if buy and rent and buy > 0:
            ratio = round((rent * 12) / buy, 4)
        results.append(
            SearchResult(
                city=r.city,
                region=r.region,
                avg_buy_price_per_sqft=buy,
                avg_rent_per_sqft=rent,
                rent_to_price_ratio=ratio,
                listing_count=r.listing_count,
            )
        )
    return results
