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


class EnrichmentPipeline:
    """Fill missing geographic fields from geo_reference table.

    Runs all lookup steps in sequence. Each step only fills fields
    that are still None/empty — never overwrites spider-provided data.
    """

    def open_spider(self, spider):
        db_url = 'postgresql://heimdall:heimdall@localhost:5433/heimdall'
        if hasattr(spider, 'settings') and hasattr(spider.settings, 'get'):
            db_url = spider.settings.get('DATABASE_URL', db_url)
        self.engine = create_engine(db_url)
        self.Session = sessionmaker(bind=self.engine)
        self._cache = {}

    def close_spider(self, spider):
        self.engine.dispose()

    def process_item(self, item, spider):
        # Step 1: lookup by postal_code
        if item.get("postal_code"):
            self._enrich_from_zip(item)

        # Step 2: lookup by city + state
        if item.get("city") and item.get("region"):
            self._enrich_from_city(item)

        # Step 3: lookup by county + state
        if item.get("county_fips"):
            self._enrich_from_county(item)

        # Step 4: lookup by state only
        if item.get("region"):
            self._enrich_from_state(item)

        # Step 5: nearest-neighbor by lat/lng (last resort)
        if item.get("latitude") and item.get("longitude") and not item.get("region"):
            self._enrich_from_coords(item)

        return item

    def _lookup(self, level, code):
        """Query geo_reference, with caching."""
        cache_key = (level, code)
        if cache_key in self._cache:
            return self._cache[cache_key]

        session = self.Session()
        try:
            result = session.execute(
                text("""
                    SELECT code, name, state_code, state_fips, county_fips,
                           county_name, city, postal_code, lat, lng
                    FROM geo_reference
                    WHERE level = :level AND code = :code
                    LIMIT 1
                """),
                {"level": level, "code": code},
            ).mappings().first()
            row = dict(result) if result else None
            self._cache[cache_key] = row
            return row
        finally:
            session.close()

    def _lookup_city(self, city, state_code):
        """Lookup city by name and state (may not match slug exactly)."""
        cache_key = ("city_lookup", city, state_code)
        if cache_key in self._cache:
            return self._cache[cache_key]

        session = self.Session()
        try:
            result = session.execute(
                text("""
                    SELECT code, name, state_code, state_fips, county_fips,
                           county_name, city, postal_code, lat, lng
                    FROM geo_reference
                    WHERE level = 'city' AND city = :city AND state_code = :state_code
                    LIMIT 1
                """),
                {"city": city.lower().strip(), "state_code": state_code.upper()},
            ).mappings().first()
            row = dict(result) if result else None
            self._cache[cache_key] = row
            return row
        finally:
            session.close()

    def _lookup_zip_for_city(self, city, state_code):
        """Find the first ZIP code that matches a city + state in geo_reference."""
        cache_key = ("zip_for_city", city, state_code)
        if cache_key in self._cache:
            return self._cache[cache_key]

        session = self.Session()
        try:
            # Find ZIPs near the city centroid
            result = session.execute(
                text("""
                    SELECT z.code AS postal_code, z.lat, z.lng
                    FROM geo_reference z
                    JOIN geo_reference c ON c.level = 'city'
                        AND c.city = :city AND c.state_code = :state_code
                    WHERE z.level = 'zip' AND z.geog IS NOT NULL AND c.geog IS NOT NULL
                    ORDER BY ST_Distance(z.geog, c.geog)
                    LIMIT 1
                """),
                {"city": city.lower().strip(), "state_code": state_code.upper()},
            ).mappings().first()
            row = dict(result) if result else None
            self._cache[cache_key] = row
            return row
        finally:
            session.close()

    def _set_if_empty(self, item, key, value):
        """Set item[key] = value only if the field is currently None or empty string."""
        if value is None:
            return
        current = item.get(key)
        if current is None or current == "":
            item[key] = value

    def _enrich_from_zip(self, item):
        """Step 1: lookup by ZIP code to fill lat/lng, then find nearest city for state/county."""
        row = self._lookup("zip", item["postal_code"])
        if not row:
            return
        self._set_if_empty(item, "latitude", float(row["lat"]) if row["lat"] else None)
        self._set_if_empty(item, "longitude", float(row["lng"]) if row["lng"] else None)
        # ZIP rows lack state/city — find the nearest city to fill those
        if row["lat"] and row["lng"] and (not item.get("region") or not item.get("city")):
            city_row = self._nearest_city(float(row["lat"]), float(row["lng"]))
            if city_row:
                self._set_if_empty(item, "region", city_row.get("state_code"))
                self._set_if_empty(item, "city", city_row.get("city"))
                self._set_if_empty(item, "county_fips", city_row.get("county_fips"))
                self._set_if_empty(item, "county_name", city_row.get("county_name"))

    def _enrich_from_county(self, item):
        """Step 3: lookup by county FIPS to fill lat/lng."""
        row = self._lookup("county", item["county_fips"])
        if not row:
            return
        self._set_if_empty(item, "latitude", float(row["lat"]) if row["lat"] else None)
        self._set_if_empty(item, "longitude", float(row["lng"]) if row["lng"] else None)
        self._set_if_empty(item, "county_name", row.get("county_name"))
        self._set_if_empty(item, "region", row.get("state_code"))

    def _enrich_from_coords(self, item):
        """Step 5: nearest-neighbor lookup by lat/lng to fill everything."""
        city_row = self._nearest_city(item["latitude"], item["longitude"])
        if not city_row:
            return
        self._set_if_empty(item, "region", city_row.get("state_code"))
        self._set_if_empty(item, "city", city_row.get("city"))
        self._set_if_empty(item, "county_fips", city_row.get("county_fips"))
        self._set_if_empty(item, "county_name", city_row.get("county_name"))

    def _nearest_city(self, lat, lng):
        """Find nearest city-level geo_reference row to given coordinates."""
        cache_key = ("nearest_city", round(lat, 2), round(lng, 2))
        if cache_key in self._cache:
            return self._cache[cache_key]

        session = self.Session()
        try:
            result = session.execute(
                text("""
                    SELECT code, name, state_code, state_fips, county_fips,
                           county_name, city, postal_code, lat, lng
                    FROM geo_reference
                    WHERE level = 'city' AND geog IS NOT NULL
                    ORDER BY geog <-> ST_SetSRID(ST_MakePoint(:lng, :lat), 4326)::geography
                    LIMIT 1
                """),
                {"lat": lat, "lng": lng},
            ).mappings().first()
            row = dict(result) if result else None
            self._cache[cache_key] = row
            return row
        finally:
            session.close()

    def _enrich_from_city(self, item):
        """Step 2: lookup by city + state to fill ZIP, county, lat/lng."""
        row = self._lookup_city(item["city"], item["region"])
        if not row:
            return
        self._set_if_empty(item, "latitude", float(row["lat"]) if row["lat"] else None)
        self._set_if_empty(item, "longitude", float(row["lng"]) if row["lng"] else None)
        self._set_if_empty(item, "county_fips", row.get("county_fips"))
        self._set_if_empty(item, "county_name", row.get("county_name"))

        # Find nearest ZIP for this city if postal_code still empty
        if not item.get("postal_code"):
            zip_row = self._lookup_zip_for_city(item["city"], item["region"])
            if zip_row:
                item["postal_code"] = zip_row["postal_code"]

    def _enrich_from_state(self, item):
        """Step 4: lookup by state to fill lat/lng."""
        row = self._lookup("state", item["region"].upper())
        if not row:
            return
        self._set_if_empty(item, "latitude", float(row["lat"]) if row["lat"] else None)
        self._set_if_empty(item, "longitude", float(row["lng"]) if row["lng"] else None)


class GeocodingPipeline:
    def __init__(self):
        self.geocoder = Nominatim(user_agent="heimdall-crawler")
        self._cache = {}

    def process_item(self, item, spider):
        # Skip if enrichment already provided coordinates
        if item.get("latitude") and item.get("longitude"):
            return item

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
                        coordinates, source_url, published_at, crawled_at,
                        county_fips, county_name
                    ) VALUES (
                        gen_random_uuid(), :source, :listing_type, :address, :city, :country,
                        :region, :postal_code, :price, :sqft, :price_per_sqft,
                        :coordinates, :source_url, :published_at, :crawled_at,
                        :county_fips, :county_name
                    )
                    ON CONFLICT (source, address, listing_type)
                    DO UPDATE SET
                        price = EXCLUDED.price,
                        sqft = EXCLUDED.sqft,
                        price_per_sqft = EXCLUDED.price_per_sqft,
                        coordinates = EXCLUDED.coordinates,
                        source_url = EXCLUDED.source_url,
                        published_at = EXCLUDED.published_at,
                        crawled_at = EXCLUDED.crawled_at,
                        county_fips = EXCLUDED.county_fips,
                        county_name = EXCLUDED.county_name
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
                    "county_fips": item.get("county_fips"),
                    "county_name": item.get("county_name"),
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
        """Refresh region_metrics at all levels when spider finishes."""
        session = sessionmaker(bind=self.engine)()
        try:
            # Shared SQL for metric computation
            metric_cols = """
                AVG(CASE WHEN l.listing_type = 'buy' AND l.price_per_sqft IS NOT NULL
                    THEN l.price_per_sqft END) AS avg_buy,
                AVG(CASE WHEN l.listing_type = 'rent' AND l.price_per_sqft IS NOT NULL
                    THEN l.price_per_sqft END) AS avg_rent,
                CASE
                    WHEN AVG(CASE WHEN l.listing_type = 'buy' AND l.price_per_sqft IS NOT NULL
                        THEN l.price_per_sqft END) > 0
                     AND AVG(CASE WHEN l.listing_type = 'rent' AND l.price_per_sqft IS NOT NULL
                        THEN l.price_per_sqft END) IS NOT NULL
                    THEN (AVG(CASE WHEN l.listing_type = 'rent' AND l.price_per_sqft IS NOT NULL
                        THEN l.price_per_sqft END) * 12)
                       / AVG(CASE WHEN l.listing_type = 'buy' AND l.price_per_sqft IS NOT NULL
                        THEN l.price_per_sqft END)
                END AS ratio,
                COUNT(*) AS cnt
            """

            # State level
            session.execute(text(f"""
                INSERT INTO region_metrics (level, code, name, country, region, lat, lng,
                    avg_buy_price_per_sqft, avg_rent_per_sqft, rent_to_price_ratio,
                    listing_count, updated_at)
                SELECT
                    'state', l.region,
                    COALESCE(g.name, l.region),
                    l.country, l.region,
                    COALESCE(AVG(ST_Y(l.coordinates::geometry)), g.lat),
                    COALESCE(AVG(ST_X(l.coordinates::geometry)), g.lng),
                    {metric_cols},
                    NOW()
                FROM listings l
                LEFT JOIN geo_reference g ON g.level = 'state' AND g.code = l.region
                GROUP BY l.region, l.country, g.name, g.lat, g.lng
                ON CONFLICT (level, code) DO UPDATE SET
                    name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                    avg_buy_price_per_sqft = EXCLUDED.avg_buy_price_per_sqft,
                    avg_rent_per_sqft = EXCLUDED.avg_rent_per_sqft,
                    rent_to_price_ratio = EXCLUDED.rent_to_price_ratio,
                    listing_count = EXCLUDED.listing_count, updated_at = EXCLUDED.updated_at
            """))

            # County level
            session.execute(text(f"""
                INSERT INTO region_metrics (level, code, name, country, region, lat, lng,
                    avg_buy_price_per_sqft, avg_rent_per_sqft, rent_to_price_ratio,
                    listing_count, updated_at)
                SELECT
                    'county', l.county_fips,
                    COALESCE(g.name, l.county_fips),
                    l.country, l.region,
                    COALESCE(AVG(ST_Y(l.coordinates::geometry)), g.lat),
                    COALESCE(AVG(ST_X(l.coordinates::geometry)), g.lng),
                    {metric_cols},
                    NOW()
                FROM listings l
                LEFT JOIN geo_reference g ON g.level = 'county' AND g.code = l.county_fips
                WHERE l.county_fips IS NOT NULL AND l.county_fips != ''
                GROUP BY l.county_fips, l.country, l.region, g.name, g.lat, g.lng
                ON CONFLICT (level, code) DO UPDATE SET
                    name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                    avg_buy_price_per_sqft = EXCLUDED.avg_buy_price_per_sqft,
                    avg_rent_per_sqft = EXCLUDED.avg_rent_per_sqft,
                    rent_to_price_ratio = EXCLUDED.rent_to_price_ratio,
                    listing_count = EXCLUDED.listing_count, updated_at = EXCLUDED.updated_at
            """))

            # City level
            session.execute(text(f"""
                INSERT INTO region_metrics (level, code, name, country, region, lat, lng,
                    avg_buy_price_per_sqft, avg_rent_per_sqft, rent_to_price_ratio,
                    listing_count, updated_at)
                SELECT
                    'city', LOWER(l.city) || '-' || LOWER(l.region),
                    COALESCE(g.name, l.city || ', ' || l.region),
                    l.country, l.region,
                    COALESCE(AVG(ST_Y(l.coordinates::geometry)), g.lat),
                    COALESCE(AVG(ST_X(l.coordinates::geometry)), g.lng),
                    {metric_cols},
                    NOW()
                FROM listings l
                LEFT JOIN geo_reference g ON g.level = 'city'
                    AND g.code = LOWER(l.city) || '-' || LOWER(l.region)
                WHERE l.city IS NOT NULL AND l.city != ''
                GROUP BY l.city, l.region, l.country, g.name, g.lat, g.lng
                ON CONFLICT (level, code) DO UPDATE SET
                    name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                    avg_buy_price_per_sqft = EXCLUDED.avg_buy_price_per_sqft,
                    avg_rent_per_sqft = EXCLUDED.avg_rent_per_sqft,
                    rent_to_price_ratio = EXCLUDED.rent_to_price_ratio,
                    listing_count = EXCLUDED.listing_count, updated_at = EXCLUDED.updated_at
            """))

            # ZIP level
            session.execute(text(f"""
                INSERT INTO region_metrics (level, code, name, country, region, lat, lng,
                    avg_buy_price_per_sqft, avg_rent_per_sqft, rent_to_price_ratio,
                    listing_count, updated_at)
                SELECT
                    'zip', l.postal_code,
                    COALESCE(g.name, l.postal_code),
                    l.country, l.region,
                    COALESCE(AVG(ST_Y(l.coordinates::geometry)), g.lat),
                    COALESCE(AVG(ST_X(l.coordinates::geometry)), g.lng),
                    {metric_cols},
                    NOW()
                FROM listings l
                LEFT JOIN geo_reference g ON g.level = 'zip' AND g.code = l.postal_code
                WHERE l.postal_code IS NOT NULL AND l.postal_code != ''
                GROUP BY l.postal_code, l.country, l.region, g.name, g.lat, g.lng
                ON CONFLICT (level, code) DO UPDATE SET
                    name = EXCLUDED.name, lat = EXCLUDED.lat, lng = EXCLUDED.lng,
                    avg_buy_price_per_sqft = EXCLUDED.avg_buy_price_per_sqft,
                    avg_rent_per_sqft = EXCLUDED.avg_rent_per_sqft,
                    rent_to_price_ratio = EXCLUDED.rent_to_price_ratio,
                    listing_count = EXCLUDED.listing_count, updated_at = EXCLUDED.updated_at
            """))

            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
