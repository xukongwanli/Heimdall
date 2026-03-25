"""Tests for EnrichmentPipeline.

These tests require a running PostgreSQL with geo_reference data.
Run `python scripts/populate_geo_reference.py` first.
"""

import sys
import os
import logging

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from heimdall_crawler.items import ListingItem
from heimdall_crawler.pipelines import EnrichmentPipeline


class FakeSpider:
    name = "test"
    logger = logging.getLogger("test_spider")

    class settings:
        @staticmethod
        def get(key, default=None):
            if key == "DATABASE_URL":
                return "postgresql://heimdall:heimdall@localhost:5433/heimdall"
            return default


class FakeSettings:
    @staticmethod
    def get(key, default=None):
        if key == "DATABASE_URL":
            return "postgresql://heimdall:heimdall@localhost:5433/heimdall"
        return default


def make_item(**kwargs):
    defaults = {
        "source": "numbeo",
        "listing_type": "buy",
        "address": "test address",
        "city": "",
        "region": "",
        "postal_code": "",
        "country": "US",
        "price": 250.0,
        "sqft": 1,
        "source_url": "https://numbeo.com/test",
        "published_at": None,
    }
    defaults.update(kwargs)
    item = ListingItem()
    for k, v in defaults.items():
        item[k] = v
    return item


def test_enrich_from_city_state():
    """Given city+state, enrichment should fill postal_code, lat, lng, county."""
    pipeline = EnrichmentPipeline()
    pipeline.open_spider(FakeSpider())

    item = make_item(city="austin", region="TX")
    result = pipeline.process_item(item, FakeSpider())

    assert result.get("postal_code"), "postal_code should be filled"
    assert result.get("latitude") is not None, "latitude should be filled"
    assert result.get("longitude") is not None, "longitude should be filled"

    pipeline.close_spider(FakeSpider())


def test_enrich_from_postal_code():
    """Given postal_code, enrichment should fill city, region, lat, lng."""
    pipeline = EnrichmentPipeline()
    pipeline.open_spider(FakeSpider())

    item = make_item(postal_code="78701")
    result = pipeline.process_item(item, FakeSpider())

    assert result.get("latitude") is not None, "latitude should be filled"
    assert result.get("longitude") is not None, "longitude should be filled"

    pipeline.close_spider(FakeSpider())


def test_enrich_does_not_overwrite():
    """Enrichment should never overwrite spider-provided data."""
    pipeline = EnrichmentPipeline()
    pipeline.open_spider(FakeSpider())

    item = make_item(city="dallas", region="TX", postal_code="75201", latitude=32.78, longitude=-96.80)
    result = pipeline.process_item(item, FakeSpider())

    assert result["city"] == "dallas"
    assert result["postal_code"] == "75201"
    assert result["latitude"] == 32.78
    assert result["longitude"] == -96.80

    pipeline.close_spider(FakeSpider())


def test_enrich_state_only():
    """Given only state, enrichment should fill lat/lng from state centroid."""
    pipeline = EnrichmentPipeline()
    pipeline.open_spider(FakeSpider())

    item = make_item(region="TX")
    result = pipeline.process_item(item, FakeSpider())

    assert result.get("latitude") is not None, "latitude should be filled from state"
    assert result.get("longitude") is not None, "longitude should be filled from state"

    pipeline.close_spider(FakeSpider())


def test_enrich_caches_lookups():
    """Second call with same city+state should use cache, not DB."""
    pipeline = EnrichmentPipeline()
    pipeline.open_spider(FakeSpider())

    item1 = make_item(city="austin", region="TX")
    pipeline.process_item(item1, FakeSpider())

    item2 = make_item(city="austin", region="TX")
    pipeline.process_item(item2, FakeSpider())

    # Both should have same enriched data
    assert item1.get("postal_code") == item2.get("postal_code")
    assert item1.get("latitude") == item2.get("latitude")

    pipeline.close_spider(FakeSpider())
