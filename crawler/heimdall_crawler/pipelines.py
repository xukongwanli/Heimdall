import re
from datetime import datetime, timezone

from geopy.geocoders import Nominatim
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from geoalchemy2.shape import from_shape
from shapely.geometry import Point


ADDRESS_ABBREVIATIONS = {
    r'\bst\b': 'street',
    r'\bave\b': 'avenue',
    r'\bblvd\b': 'boulevard',
    r'\bdr\b': 'drive',
    r'\bln\b': 'lane',
    r'\brd\b': 'road',
    r'\bct\b': 'court',
    r'\bpl\b': 'place',
    r'\bapt\b': 'apartment',
    r'\bste\b': 'suite',
}


class CleaningPipeline:
    # Pattern: "123 Main St, Austin, TX 78701" or "123 Main St, Austin TX 78701"
    _address_tail_re = re.compile(
        r',\s*([a-zA-Z\s]+),?\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)\s*$'
    )

    def process_item(self, item, spider):
        raw_address = item.get("address", "")
        # Try to extract city/state/zip from address tail if spider didn't provide them
        if not item.get("city") or not item.get("postal_code"):
            match = self._address_tail_re.search(raw_address)
            if match:
                if not item.get("city"):
                    item["city"] = match.group(1).strip()
                if not item.get("postal_code"):
                    item["postal_code"] = match.group(3)
                # Strip the city/state/zip tail from address
                raw_address = raw_address[:match.start()]

        item["address"] = self._normalize_address(raw_address)
        item["city"] = item.get("city", "").strip().lower()
        item["price"] = self._parse_number(item.get("price"), allow_zero=True)
        item["sqft"] = self._parse_number(item.get("sqft"), allow_zero=False)

        if item["sqft"] and item["sqft"] > 0 and item["price"]:
            item["price_per_sqft"] = round(item["price"] / item["sqft"], 2)
        else:
            item["price_per_sqft"] = None

        if not item.get("published_at"):
            item["published_at"] = datetime.now(timezone.utc)

        item["crawled_at"] = datetime.now(timezone.utc)
        return item

    def _normalize_address(self, address):
        address = address.strip().lower()
        # Normalize unit notation before abbreviation expansion to avoid double-expansion
        # e.g. "Apt #4" -> "apt 4" (the "apt" abbreviation will then expand to "apartment")
        address = re.sub(r'#\s*(\d+)', r'\1', address)
        # Expand abbreviations
        for pattern, replacement in ADDRESS_ABBREVIATIONS.items():
            address = re.sub(pattern, replacement, address)
        # Collapse whitespace
        address = re.sub(r'\s+', ' ', address)
        return address

    def _parse_number(self, value, allow_zero=False):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            value = re.sub(r'[^\d.]', '', str(value))
            if not value:
                return None
            result = float(value)
        if result < 0:
            return None
        if result == 0 and not allow_zero:
            return None
        return result


class GeocodingPipeline:
    def __init__(self):
        self.geocoder = Nominatim(user_agent="heimdall-crawler")
        self._cache = {}

    def process_item(self, item, spider):
        address_key = f"{item.get('address')}, {item.get('city')}, {item.get('region')} {item.get('postal_code')}"

        if address_key in self._cache:
            item["latitude"], item["longitude"] = self._cache[address_key]
            return item

        try:
            location = self.geocoder.geocode(address_key)
            if location:
                item["latitude"] = location.latitude
                item["longitude"] = location.longitude
            else:
                item["latitude"] = None
                item["longitude"] = None
        except Exception:
            item["latitude"] = None
            item["longitude"] = None

        self._cache[address_key] = (item.get("latitude"), item.get("longitude"))
        return item


class PostgresPipeline:
    def open_spider(self, spider):
        db_url = 'postgresql://heimdall:heimdall@localhost:5433/heimdall'
        if hasattr(spider, 'settings') and hasattr(spider.settings, 'get'):
            db_url = spider.settings.get('DATABASE_URL', db_url)
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)

    def close_spider(self, spider):
        self.engine.dispose()

    def process_item(self, item, spider):
        session = self.Session()
        try:
            coords = None
            if item.get("latitude") and item.get("longitude"):
                coords = from_shape(Point(item["longitude"], item["latitude"]), srid=4326)

            session.execute(
                text("""
                    INSERT INTO listings (
                        id, source, listing_type, address, city, country,
                        region, postal_code, price, sqft, price_per_sqft,
                        coordinates, source_url, published_at, crawled_at
                    ) VALUES (
                        gen_random_uuid(), :source, :listing_type, :address, :city, :country,
                        :region, :postal_code, :price, :sqft, :price_per_sqft,
                        :coordinates, :source_url, :published_at, :crawled_at
                    )
                    ON CONFLICT (source, address, listing_type)
                    DO UPDATE SET
                        price = EXCLUDED.price,
                        sqft = EXCLUDED.sqft,
                        price_per_sqft = EXCLUDED.price_per_sqft,
                        coordinates = EXCLUDED.coordinates,
                        source_url = EXCLUDED.source_url,
                        published_at = EXCLUDED.published_at,
                        crawled_at = EXCLUDED.crawled_at
                    WHERE EXCLUDED.published_at > listings.published_at
                """),
                {
                    "source": item["source"],
                    "listing_type": item["listing_type"],
                    "address": item["address"],
                    "city": item.get("city", ""),
                    "country": item.get("country", "US"),
                    "region": item.get("region", ""),
                    "postal_code": item.get("postal_code", ""),
                    "price": item["price"],
                    "sqft": item.get("sqft"),
                    "price_per_sqft": item.get("price_per_sqft"),
                    "coordinates": str(coords) if coords else None,
                    "source_url": item["source_url"],
                    "published_at": item["published_at"],
                    "crawled_at": item.get("crawled_at"),
                },
            )
            session.commit()
        except Exception as e:
            session.rollback()
            spider.logger.error(f"Failed to upsert listing: {e}")
            raise
        finally:
            session.close()
        return item


class MetricsRefreshPipeline:
    def open_spider(self, spider):
        db_url = 'postgresql://heimdall:heimdall@localhost:5433/heimdall'
        if hasattr(spider, 'settings') and hasattr(spider.settings, 'get'):
            db_url = spider.settings.get('DATABASE_URL', db_url)
        self.engine = create_engine(db_url)

    def process_item(self, item, spider):
        return item

    def close_spider(self, spider):
        """Refresh zip_metrics when spider finishes."""
        session = sessionmaker(bind=self.engine)()
        try:
            session.execute(text("""
                INSERT INTO zip_metrics (postal_code, country, region, lat, lng,
                    avg_buy_price_per_sqft, avg_rent_per_sqft, rent_to_price_ratio,
                    listing_count, updated_at)
                SELECT
                    l.postal_code,
                    l.country,
                    l.region,
                    AVG(ST_Y(l.coordinates::geometry)) AS lat,
                    AVG(ST_X(l.coordinates::geometry)) AS lng,
                    AVG(CASE WHEN l.listing_type = 'buy' AND l.price_per_sqft IS NOT NULL THEN l.price_per_sqft END) AS avg_buy,
                    AVG(CASE WHEN l.listing_type = 'rent' AND l.price_per_sqft IS NOT NULL THEN l.price_per_sqft END) AS avg_rent,
                    CASE
                        WHEN AVG(CASE WHEN l.listing_type = 'buy' AND l.price_per_sqft IS NOT NULL THEN l.price_per_sqft END) > 0
                         AND AVG(CASE WHEN l.listing_type = 'rent' AND l.price_per_sqft IS NOT NULL THEN l.price_per_sqft END) IS NOT NULL
                        THEN (AVG(CASE WHEN l.listing_type = 'rent' AND l.price_per_sqft IS NOT NULL THEN l.price_per_sqft END) * 12)
                           / AVG(CASE WHEN l.listing_type = 'buy' AND l.price_per_sqft IS NOT NULL THEN l.price_per_sqft END)
                    END AS ratio,
                    COUNT(*),
                    NOW()
                FROM listings l
                GROUP BY l.postal_code, l.country, l.region
                ON CONFLICT (postal_code) DO UPDATE SET
                    country = EXCLUDED.country,
                    region = EXCLUDED.region,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    avg_buy_price_per_sqft = EXCLUDED.avg_buy_price_per_sqft,
                    avg_rent_per_sqft = EXCLUDED.avg_rent_per_sqft,
                    rent_to_price_ratio = EXCLUDED.rent_to_price_ratio,
                    listing_count = EXCLUDED.listing_count,
                    updated_at = EXCLUDED.updated_at
            """))
            session.commit()
        except Exception as e:
            session.rollback()
            raise
        finally:
            session.close()
