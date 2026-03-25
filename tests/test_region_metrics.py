"""Tests for MetricsRefreshPipeline writing to region_metrics."""

import sys
import os
import uuid
import logging
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from heimdall_crawler.pipelines import MetricsRefreshPipeline

DB_URL = "postgresql://heimdall:heimdall@localhost:5433/heimdall"


class FakeSpider:
    name = "test"
    logger = logging.getLogger("test_spider")

    class settings:
        @staticmethod
        def get(key, default=None):
            if key == "DATABASE_URL":
                return DB_URL
            return default


def test_metrics_refresh_writes_state_level():
    """MetricsRefreshPipeline should aggregate listings at state level."""
    engine = create_engine(DB_URL)
    session = sessionmaker(bind=engine)()

    tag = uuid.uuid4().hex[:6]
    now = datetime.now(timezone.utc)

    try:
        # Insert test listings with unique region tag
        session.execute(text("""
            INSERT INTO listings (id, source, listing_type, address, city, country, region,
                postal_code, price, sqft, price_per_sqft, source_url, published_at, crawled_at)
            VALUES
                (gen_random_uuid(), 'test', 'buy',  :addr_buy,  'testcity', 'US', :region, '00001', 120000, 1000, 120, 'http://test', :now, :now),
                (gen_random_uuid(), 'test', 'rent', :addr_rent, 'testcity', 'US', :region, '00001', 1200, 1000, 1.2, 'http://test', :now, :now)
        """), {"addr_buy": f"buy-{tag}", "addr_rent": f"rent-{tag}", "region": f"T{tag[:1]}", "now": now})
        session.commit()

        region_code = f"T{tag[:1]}"

        # Run metrics refresh
        pipeline = MetricsRefreshPipeline()
        pipeline.engine = engine
        pipeline.close_spider(FakeSpider())

        # Check state-level row exists in region_metrics
        result = session.execute(
            text("SELECT * FROM region_metrics WHERE level = 'state' AND code = :code"),
            {"code": region_code}
        ).mappings().first()

        assert result is not None, f"Expected state-level row for {region_code}"
        assert float(result["avg_buy_price_per_sqft"]) == 120.0
        assert float(result["avg_rent_per_sqft"]) == 1.2

    finally:
        session.execute(text("DELETE FROM region_metrics WHERE code = :code"), {"code": region_code})
        session.execute(text("DELETE FROM listings WHERE address IN (:a1, :a2)"), {"a1": f"buy-{tag}", "a2": f"rent-{tag}"})
        session.commit()
        session.close()
