import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.items import ListingItem
from heimdall_crawler.pipelines import CleaningPipeline


class FakeSpider:
    name = "test"


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
