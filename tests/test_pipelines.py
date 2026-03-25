import sys
import os
import logging
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.items import ListingItem
from heimdall_crawler.pipelines import CleaningPipeline


class FakeSpider:
    name = "test"
    logger = logging.getLogger("test_spider")


def make_item(**kwargs):
    defaults = {
        "source": "zillow",
        "listing_type": "buy",
        "address": "123 Main St",
        "city": "Austin",
        "region": "TX",
        "postal_code": "78701",
        "country": "US",
        "price": "$450,000",
        "sqft": "1,800",
        "source_url": "https://zillow.com/123",
        "published_at": None,
    }
    defaults.update(kwargs)
    item = ListingItem()
    for k, v in defaults.items():
        item[k] = v
    return item


def test_cleaning_normalizes_address():
    pipeline = CleaningPipeline()
    item = make_item(address="  123 Main St, Apt #4  ")
    result = pipeline.process_item(item, FakeSpider())
    assert result["address"] == "123 main street, apartment 4"


def test_cleaning_expands_abbreviations():
    pipeline = CleaningPipeline()
    item = make_item(address="456 Oak Ave")
    result = pipeline.process_item(item, FakeSpider())
    assert result["address"] == "456 oak avenue"


def test_cleaning_parses_price_string():
    pipeline = CleaningPipeline()
    item = make_item(price="$450,000")
    result = pipeline.process_item(item, FakeSpider())
    assert result["price"] == 450000


def test_cleaning_parses_sqft_string():
    pipeline = CleaningPipeline()
    item = make_item(sqft="1,800 sq ft")
    result = pipeline.process_item(item, FakeSpider())
    assert result["sqft"] == 1800


def test_cleaning_computes_price_per_sqft():
    pipeline = CleaningPipeline()
    item = make_item(price="450000", sqft="1800")
    result = pipeline.process_item(item, FakeSpider())
    assert result["price_per_sqft"] == 250.0


def test_cleaning_null_sqft():
    pipeline = CleaningPipeline()
    item = make_item(price="450000", sqft=None)
    result = pipeline.process_item(item, FakeSpider())
    assert result["sqft"] is None
    assert result["price_per_sqft"] is None


def test_cleaning_zero_sqft():
    pipeline = CleaningPipeline()
    item = make_item(price="450000", sqft="0")
    result = pipeline.process_item(item, FakeSpider())
    assert result["price_per_sqft"] is None


def test_cleaning_published_at_fallback():
    """When published_at is None, it should be set to crawled_at by pipeline."""
    pipeline = CleaningPipeline()
    item = make_item(published_at=None)
    result = pipeline.process_item(item, FakeSpider())
    assert result["published_at"] is not None  # should be set to now


from unittest.mock import MagicMock
from heimdall_crawler.pipelines import GeocodingPipeline


def test_geocoding_sets_coordinates():
    pipeline = GeocodingPipeline()
    pipeline.geocoder = MagicMock()
    pipeline.geocoder.geocode.return_value = MagicMock(latitude=30.2672, longitude=-97.7431)

    item = make_item()
    item["address"] = "123 main street"
    item["city"] = "austin"
    item["region"] = "TX"
    item["postal_code"] = "78701"
    result = pipeline.process_item(item, FakeSpider())
    assert result["latitude"] == 30.2672
    assert result["longitude"] == -97.7431


def test_geocoding_handles_failure():
    pipeline = GeocodingPipeline()
    pipeline.geocoder = MagicMock()
    pipeline.geocoder.geocode.return_value = None

    item = make_item()
    result = pipeline.process_item(item, FakeSpider())
    assert result["latitude"] is None
    assert result["longitude"] is None


import uuid
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Need to add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from backend.app.models import Base, Listing
from heimdall_crawler.pipelines import PostgresPipeline, MetricsRefreshPipeline


DB_URL = "postgresql://localhost/heimdall"


def setup_module():
    """Ensure DB tables exist before running pipeline tests."""
    engine = create_engine(DB_URL)
    Base.metadata.create_all(engine)


def test_postgres_pipeline_inserts_listing():
    pipeline = PostgresPipeline()
    pipeline.open_spider(FakeSpider())

    item = make_item(price=450000, sqft=1800)
    item["price_per_sqft"] = 250.0
    item["latitude"] = 30.2672
    item["longitude"] = -97.7431
    item["crawled_at"] = datetime.now(timezone.utc)
    item["published_at"] = datetime.now(timezone.utc)
    item["address"] = f"test-{uuid.uuid4().hex[:8]}"  # unique address

    pipeline.process_item(item, FakeSpider())

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    result = session.query(Listing).filter_by(address=item["address"]).first()
    assert result is not None
    assert result.price == 450000
    session.delete(result)
    session.commit()
    session.close()
    pipeline.close_spider(FakeSpider())


def test_postgres_pipeline_upserts_newer():
    pipeline = PostgresPipeline()
    pipeline.open_spider(FakeSpider())

    addr = f"upsert-test-{uuid.uuid4().hex[:8]}"
    now = datetime.now(timezone.utc)

    item1 = make_item(price=400000, sqft=1600)
    item1["price_per_sqft"] = 250.0
    item1["latitude"] = 30.0
    item1["longitude"] = -97.0
    item1["crawled_at"] = now
    item1["published_at"] = now - timedelta(days=1)
    item1["address"] = addr

    item2 = make_item(price=420000, sqft=1600)
    item2["price_per_sqft"] = 262.5
    item2["latitude"] = 30.0
    item2["longitude"] = -97.0
    item2["crawled_at"] = now
    item2["published_at"] = now  # newer
    item2["address"] = addr

    pipeline.process_item(item1, FakeSpider())
    pipeline.process_item(item2, FakeSpider())

    engine = create_engine(DB_URL)
    Session = sessionmaker(bind=engine)
    session = Session()
    result = session.query(Listing).filter_by(address=addr).first()
    assert result.price == 420000  # newer listing's price
    session.delete(result)
    session.commit()
    session.close()
    pipeline.close_spider(FakeSpider())


# test_metrics_refresh_computes_ratios removed — will be replaced in Task 6
# with a new test against region_metrics.
