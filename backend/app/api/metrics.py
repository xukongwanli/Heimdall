from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_session
from backend.app.models import RegionMetrics
from backend.app.schemas import MetricPoint

router = APIRouter()

METRIC_COLUMNS = {
    "rent_to_price_ratio": RegionMetrics.rent_to_price_ratio,
    "avg_buy_price_per_sqft": RegionMetrics.avg_buy_price_per_sqft,
    "avg_rent_per_sqft": RegionMetrics.avg_rent_per_sqft,
}

VALID_LEVELS = {"state", "county", "city", "zip"}


@router.get("/metrics", response_model=list[MetricPoint])
def get_metrics(
    metric: str = Query("rent_to_price_ratio", enum=list(METRIC_COLUMNS.keys())),
    level: str = Query("state", enum=list(VALID_LEVELS)),
    region: str | None = Query(None),
    session: Session = Depends(get_session),
):
    col = METRIC_COLUMNS[metric]
    q = session.query(
        RegionMetrics.level,
        RegionMetrics.code,
        RegionMetrics.name,
        RegionMetrics.lat,
        RegionMetrics.lng,
        col.label("value"),
        RegionMetrics.region,
        RegionMetrics.listing_count,
    ).filter(RegionMetrics.level == level)

    if region:
        q = q.filter(RegionMetrics.region == region.upper())

    q = q.filter(col.isnot(None))

    rows = q.all()
    return [
        MetricPoint(
            level=r.level,
            code=r.code,
            name=r.name,
            lat=float(r.lat) if r.lat else None,
            lng=float(r.lng) if r.lng else None,
            value=float(r.value) if r.value else None,
            region=r.region,
            listing_count=r.listing_count,
        )
        for r in rows
    ]
