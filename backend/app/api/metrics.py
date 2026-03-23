from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from backend.app.database import get_session
from backend.app.models import ZipMetrics
from backend.app.schemas import MetricPoint

router = APIRouter()

METRIC_COLUMNS = {
    "rent_to_price_ratio": ZipMetrics.rent_to_price_ratio,
    "avg_buy_price_per_sqft": ZipMetrics.avg_buy_price_per_sqft,
    "avg_rent_per_sqft": ZipMetrics.avg_rent_per_sqft,
}


@router.get("/metrics", response_model=list[MetricPoint])
def get_metrics(
    metric: str = Query("rent_to_price_ratio", enum=list(METRIC_COLUMNS.keys())),
    region: str | None = Query(None),
    session: Session = Depends(get_session),
):
    col = METRIC_COLUMNS[metric]
    q = session.query(
        ZipMetrics.postal_code,
        ZipMetrics.lat,
        ZipMetrics.lng,
        col.label("value"),
        ZipMetrics.region,
        ZipMetrics.listing_count,
    )

    if region:
        q = q.filter(ZipMetrics.region == region.upper())

    q = q.filter(col.isnot(None))

    rows = q.all()
    return [
        MetricPoint(
            postal_code=r.postal_code,
            lat=float(r.lat) if r.lat else None,
            lng=float(r.lng) if r.lng else None,
            value=float(r.value) if r.value else None,
            region=r.region,
            listing_count=r.listing_count,
        )
        for r in rows
    ]
