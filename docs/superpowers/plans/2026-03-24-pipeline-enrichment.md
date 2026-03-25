# Pipeline Enrichment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the empty choropleth map by adding a geo reference database, enrichment pipeline, and multi-level metrics aggregation.

**Architecture:** Census gazetteer data populates a `geo_reference` lookup table. A new `EnrichmentPipeline` fills missing geographic fields on crawled listings. `MetricsRefreshPipeline` aggregates into a new `region_metrics` table at state/county/city/ZIP levels. The API and frontend are updated to query by level.

**Tech Stack:** Python/SQLAlchemy/Alembic (backend), Scrapy (crawler), FastAPI, Nuxt 3/Vue 3/Leaflet (frontend), PostgreSQL/PostGIS

**Spec:** `docs/superpowers/specs/2026-03-24-pipeline-enrichment-design.md`

---

## File Structure

### New files
| File | Responsibility |
|------|---------------|
| `backend/alembic/versions/*_geo_reference_and_region_metrics.py` | Migration: create `geo_reference`, create `region_metrics`, drop `zip_metrics`, add `county_fips`/`county_name` to `listings` |
| `scripts/populate_geo_reference.py` | Download Census gazetteers, parse TSV, bulk-insert into `geo_reference` |
| `tests/test_enrichment.py` | Unit tests for `EnrichmentPipeline` |
| `tests/test_region_metrics.py` | Tests for `MetricsRefreshPipeline` writing to `region_metrics` |

### Modified files
| File | What changes |
|------|-------------|
| `backend/app/models.py` | Add `GeoReference`, `RegionMetrics` models; remove `ZipMetrics`; add `county_fips`/`county_name` to `Listing` |
| `backend/app/schemas.py` | Update `MetricPoint` → `level`, `code`, `name` fields |
| `backend/app/api/metrics.py` | Query `RegionMetrics` with `level` param |
| `crawler/heimdall_crawler/items.py` | Add `county_fips`, `county_name` fields |
| `crawler/heimdall_crawler/pipelines.py` | Add `EnrichmentPipeline`; update `GeocodingPipeline`, `PostgresPipeline`, `MetricsRefreshPipeline` |
| `crawler/heimdall_crawler/settings.py` | Register `EnrichmentPipeline` at 150 |
| `crawler/requirements.txt` | Add `requests` (used by populate script, which shares crawler venv) |
| `frontend/pages/index.vue` | Wire up `levelChange` event from ChoroplethMap |
| `frontend/utils/aggregate.ts` | New `MetricPoint` interface, replace with `aggregateByCode` |
| `frontend/composables/useMetrics.ts` | Add `level` param, composite cache key |
| `frontend/components/ChoroplethMap.vue` | Fetch by level on zoom, use `aggregateByCode` |
| `frontend/server/api/metrics.get.ts` | Forward `level` param |
| `tests/test_pipelines.py` | Update `MetricsRefreshPipeline` test for `region_metrics` |

---

## Task 1: Database Migration — `geo_reference` and `region_metrics`

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/*_geo_reference_and_region_metrics.py`

- [ ] **Step 1: Update SQLAlchemy models**

Replace `ZipMetrics` with `GeoReference` and `RegionMetrics`, add columns to `Listing` in `backend/app/models.py`:

```python
# Add these imports at the top alongside existing ones
from geoalchemy2 import Geography

# Add to Listing class, after line 28 (crawled_at):
    county_fips = Column(String(5), nullable=True)
    county_name = Column(Text, nullable=True)

# Add index to Listing.__table_args__ tuple (before the closing parenthesis):
        Index("ix_listings_county_fips", "county_fips"),

# Replace the entire ZipMetrics class (lines 42-54) with:

class GeoReference(Base):
    __tablename__ = "geo_reference"

    id = Column(Integer, primary_key=True, autoincrement=True)
    level = Column(String(10), nullable=False)       # state, county, city, zip
    code = Column(Text, nullable=False)               # TX, 48453, austin-tx, 78701
    name = Column(Text, nullable=False)
    state_code = Column(String(2), nullable=True)
    state_fips = Column(String(2), nullable=True)
    county_fips = Column(String(5), nullable=True)
    county_name = Column(Text, nullable=True)
    city = Column(Text, nullable=True)
    postal_code = Column(Text, nullable=True)
    lat = Column(Numeric, nullable=True)
    lng = Column(Numeric, nullable=True)
    geog = Column(Geography("POINT", srid=4326), nullable=True)
    land_area_sqft = Column(Numeric, nullable=True)
    water_area_sqft = Column(Numeric, nullable=True)

    __table_args__ = (
        UniqueConstraint("level", "code", name="uq_geo_ref_level_code"),
        Index("ix_geo_ref_level_state", "level", "state_code"),
        Index("ix_geo_ref_level_city_state", "level", "city", "state_code"),
        Index("ix_geo_ref_geog", "geog", postgresql_using="gist"),
    )


class RegionMetrics(Base):
    __tablename__ = "region_metrics"

    level = Column(String(10), nullable=False, primary_key=True)
    code = Column(Text, nullable=False, primary_key=True)
    name = Column(Text, nullable=False)
    country = Column(String(2), nullable=False, default="US")
    region = Column(Text, nullable=False)
    lat = Column(Numeric, nullable=True)
    lng = Column(Numeric, nullable=True)
    avg_buy_price_per_sqft = Column(Numeric, nullable=True)
    avg_rent_per_sqft = Column(Numeric, nullable=True)
    rent_to_price_ratio = Column(Numeric, nullable=True)
    listing_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime(timezone=True), nullable=False)
```

- [ ] **Step 2: Generate Alembic migration**

Run from project root:
```bash
cd backend && source .venv/bin/activate && alembic revision --autogenerate -m "add geo_reference and region_metrics, drop zip_metrics"
```

- [ ] **Step 3: Review and fix the generated migration**

The autogenerated migration may need manual adjustments. Verify it:
1. Drops `zip_metrics` table
2. Creates `geo_reference` table with `geog` GEOGRAPHY column
3. Creates `region_metrics` table with composite PK `(level, code)`
4. Adds `county_fips` and `county_name` columns to `listings`
5. Adds `ix_listings_county_fips` index

- [ ] **Step 4: Run the migration**

```bash
cd backend && alembic upgrade head
```
Expected: Migration applies without errors.

- [ ] **Step 5: Verify tables exist**

```bash
PGPASSWORD=heimdall psql -h localhost -p 5433 -U heimdall -d heimdall -c "\dt"
```
Expected: `geo_reference`, `region_metrics`, `listings` tables present; `zip_metrics` gone.

- [ ] **Step 6: Fix test_pipelines.py import to avoid broken ZipMetrics reference**

In `tests/test_pipelines.py`, line 131, change:
```python
from backend.app.models import Base, Listing, ZipMetrics
```
to:
```python
from backend.app.models import Base, Listing
```

Also comment out or remove the `test_metrics_refresh_computes_ratios` test (lines 207-246) — it will be replaced in Task 6 with a new test against `region_metrics`.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/ tests/test_pipelines.py
git commit -m "feat: add geo_reference and region_metrics tables, drop zip_metrics"
```

---

## Task 2: Census Gazetteer Population Script

**Files:**
- Create: `scripts/populate_geo_reference.py`
- Modify: `crawler/requirements.txt` (add `requests`)

- [ ] **Step 1: Add `requests` to crawler requirements**

Append to `crawler/requirements.txt`:
```
requests==2.32.3
```

- [ ] **Step 2: Write the population script**

Create `scripts/populate_geo_reference.py`:

```python
"""Download US Census Bureau gazetteer files and populate geo_reference table.

Usage:
    python scripts/populate_geo_reference.py

Downloads four TSV files from census.gov (~5 MB total), parses them, and
bulk-upserts rows into the geo_reference table. Idempotent — safe to re-run.
"""

import io
import re
import zipfile

import requests
from sqlalchemy import create_engine, text

DB_URL = "postgresql://heimdall:heimdall@localhost:5433/heimdall"

CENSUS_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer"

GAZETTEER_URLS = {
    "state": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_state_national.zip",
    "county": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_counties_national.zip",
    "place": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_place_national.zip",
    "zcta": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_zcta_national.zip",
}

# State FIPS -> abbreviation mapping
STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}

SQMI_TO_SQFT = 27_878_400  # 1 square mile = 27,878,400 square feet


def download_and_extract(url: str) -> str:
    """Download a zip file and return the contents of the first .txt file inside."""
    print(f"  Downloading {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
        if not txt_files:
            raise ValueError(f"No .txt file found in {url}")
        return zf.read(txt_files[0]).decode("utf-8", errors="replace")


def parse_tsv(content: str) -> list[dict]:
    """Parse a tab-separated gazetteer file into a list of dicts."""
    lines = content.strip().split("\n")
    headers = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        fields = line.split("\t")
        row = {}
        for i, h in enumerate(headers):
            row[h] = fields[i].strip() if i < len(fields) else ""
        rows.append(row)
    return rows


def make_city_slug(city_name: str) -> str:
    """Convert city name to slug: lowercase, hyphens, no special chars."""
    slug = city_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def safe_float(val: str) -> float | None:
    """Parse a string to float, returning None on failure."""
    try:
        return float(val.replace(",", "")) if val.strip() else None
    except ValueError:
        return None


def process_states(rows: list[dict]) -> list[dict]:
    """Process state gazetteer rows."""
    results = []
    for r in rows:
        usps = r.get("USPS", "").strip()
        geoid = r.get("GEOID", "").strip()
        if not usps:
            continue
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "state",
            "code": usps,
            "name": r.get("NAME", usps),
            "state_code": usps,
            "state_fips": geoid,
            "county_fips": None,
            "county_name": None,
            "city": None,
            "postal_code": None,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def process_counties(rows: list[dict]) -> list[dict]:
    """Process county gazetteer rows."""
    results = []
    for r in rows:
        geoid = r.get("GEOID", "").strip()
        if not geoid or len(geoid) < 4:
            continue
        state_fips = geoid[:2]
        state_code = STATE_FIPS_TO_ABBR.get(state_fips, "")
        if not state_code:
            continue
        name = r.get("NAME", "")
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "county",
            "code": geoid,
            "name": name,
            "state_code": state_code,
            "state_fips": state_fips,
            "county_fips": geoid,
            "county_name": name,
            "city": None,
            "postal_code": None,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def process_places(rows: list[dict]) -> list[dict]:
    """Process place (city) gazetteer rows."""
    results = []
    for r in rows:
        geoid = r.get("GEOID", "").strip()
        if not geoid or len(geoid) < 3:
            continue
        state_fips = geoid[:2]
        state_code = STATE_FIPS_TO_ABBR.get(state_fips, "")
        if not state_code:
            continue
        name = r.get("NAME", "").strip()
        # Remove suffixes like "city", "town", "CDP", "village" for matching
        city_clean = re.sub(r"\s+(city|town|CDP|village|borough|municipality)$", "", name, flags=re.IGNORECASE)
        slug = make_city_slug(city_clean)
        code = f"{slug}-{state_code.lower()}"
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "city",
            "code": code,
            "name": f"{city_clean}, {state_code}",
            "state_code": state_code,
            "state_fips": state_fips,
            "county_fips": None,
            "county_name": None,
            "city": city_clean.lower(),
            "postal_code": None,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def process_zctas(rows: list[dict]) -> list[dict]:
    """Process ZCTA (ZIP code) gazetteer rows."""
    results = []
    for r in rows:
        geoid = r.get("GEOID", "").strip()
        if not geoid or len(geoid) != 5:
            continue
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "zip",
            "code": geoid,
            "name": geoid,
            "state_code": None,  # ZCTAs don't come with state — filled via spatial join later or enrichment
            "state_fips": None,
            "county_fips": None,
            "county_name": None,
            "city": None,
            "postal_code": geoid,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def upsert_rows(engine, rows: list[dict]) -> int:
    """Bulk upsert rows into geo_reference. Returns count inserted/updated."""
    if not rows:
        return 0
    with engine.begin() as conn:
        for row in rows:
            geog_expr = f"ST_SetSRID(ST_MakePoint({row['lng']}, {row['lat']}), 4326)::geography" if row["lat"] and row["lng"] else "NULL"
            conn.execute(text(f"""
                INSERT INTO geo_reference (level, code, name, state_code, state_fips,
                    county_fips, county_name, city, postal_code, lat, lng, geog,
                    land_area_sqft, water_area_sqft)
                VALUES (:level, :code, :name, :state_code, :state_fips,
                    :county_fips, :county_name, :city, :postal_code, :lat, :lng,
                    {geog_expr},
                    :land_area_sqft, :water_area_sqft)
                ON CONFLICT (level, code) DO UPDATE SET
                    name = EXCLUDED.name,
                    state_code = EXCLUDED.state_code,
                    state_fips = EXCLUDED.state_fips,
                    county_fips = EXCLUDED.county_fips,
                    county_name = EXCLUDED.county_name,
                    city = EXCLUDED.city,
                    postal_code = EXCLUDED.postal_code,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    geog = EXCLUDED.geog,
                    land_area_sqft = EXCLUDED.land_area_sqft,
                    water_area_sqft = EXCLUDED.water_area_sqft
            """), row)
    return len(rows)


def main():
    engine = create_engine(DB_URL)
    total = 0

    print("Downloading and processing Census gazetteer files...")

    # States
    content = download_and_extract(GAZETTEER_URLS["state"])
    rows = process_states(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  States: {count} rows")
    total += count

    # Counties
    content = download_and_extract(GAZETTEER_URLS["county"])
    rows = process_counties(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  Counties: {count} rows")
    total += count

    # Places (cities)
    content = download_and_extract(GAZETTEER_URLS["place"])
    rows = process_places(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  Places: {count} rows")
    total += count

    # ZCTAs (ZIP codes)
    content = download_and_extract(GAZETTEER_URLS["zcta"])
    rows = process_zctas(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  ZCTAs: {count} rows")
    total += count

    print(f"\nDone. Total rows upserted: {total}")
    engine.dispose()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the population script**

```bash
cd /Users/yourstruly/Documents/heimdall
source crawler/.venv/bin/activate  # or backend/.venv — needs requests + sqlalchemy
pip install requests
python scripts/populate_geo_reference.py
```

Expected output:
```
Downloading and processing Census gazetteer files...
  States: ~52 rows
  Counties: ~3200 rows
  Places: ~30000 rows
  ZCTAs: ~33000 rows
Done. Total rows upserted: ~66000
```

- [ ] **Step 4: Verify data**

```bash
PGPASSWORD=heimdall psql -h localhost -p 5433 -U heimdall -d heimdall -c "SELECT level, COUNT(*) FROM geo_reference GROUP BY level ORDER BY level;"
```

Expected: 4 rows with counts for city, county, state, zip.

- [ ] **Step 5: Commit**

```bash
git add scripts/populate_geo_reference.py crawler/requirements.txt
git commit -m "feat: add Census gazetteer population script for geo_reference"
```

---

## Task 3: Crawler Item & Settings Updates

**Files:**
- Modify: `crawler/heimdall_crawler/items.py`
- Modify: `crawler/heimdall_crawler/settings.py`

- [ ] **Step 1: Add fields to ListingItem**

In `crawler/heimdall_crawler/items.py`, add after line 20 (`longitude`):

```python
    county_fips = scrapy.Field()     # set by EnrichmentPipeline
    county_name = scrapy.Field()     # set by EnrichmentPipeline
```

- [ ] **Step 2: Register EnrichmentPipeline in settings**

In `crawler/heimdall_crawler/settings.py`, update `ITEM_PIPELINES` (lines 28-33) to:

```python
ITEM_PIPELINES = {
    "heimdall_crawler.pipelines.CleaningPipeline": 100,
    "heimdall_crawler.pipelines.EnrichmentPipeline": 150,
    "heimdall_crawler.pipelines.GeocodingPipeline": 200,
    "heimdall_crawler.pipelines.PostgresPipeline": 300,
    "heimdall_crawler.pipelines.MetricsRefreshPipeline": 400,
}
```

- [ ] **Step 3: Commit**

```bash
git add crawler/heimdall_crawler/items.py crawler/heimdall_crawler/settings.py
git commit -m "feat: add county fields to ListingItem, register EnrichmentPipeline"
```

---

## Task 4: EnrichmentPipeline

**Files:**
- Modify: `crawler/heimdall_crawler/pipelines.py` (add new class after `CleaningPipeline`)
- Create: `tests/test_enrichment.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_enrichment.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/yourstruly/Documents/heimdall
python -m pytest tests/test_enrichment.py -v
```

Expected: FAIL — `EnrichmentPipeline` does not exist yet.

- [ ] **Step 3: Write EnrichmentPipeline**

In `crawler/heimdall_crawler/pipelines.py`, add after `CleaningPipeline` class (after line 87):

```python
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
        """Step 3: lookup by state to fill lat/lng."""
        row = self._lookup("state", item["region"].upper())
        if not row:
            return
        self._set_if_empty(item, "latitude", float(row["lat"]) if row["lat"] else None)
        self._set_if_empty(item, "longitude", float(row["lng"]) if row["lng"] else None)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/test_enrichment.py -v
```

Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add crawler/heimdall_crawler/pipelines.py tests/test_enrichment.py
git commit -m "feat: add EnrichmentPipeline to fill missing geo fields from geo_reference"
```

---

## Task 5: Update GeocodingPipeline and PostgresPipeline

**Files:**
- Modify: `crawler/heimdall_crawler/pipelines.py`

- [ ] **Step 1: Update GeocodingPipeline to skip when lat/lng present**

Replace `GeocodingPipeline.process_item` (lines 94-114) with:

```python
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
```

- [ ] **Step 2: Update PostgresPipeline INSERT to include county columns**

Replace the INSERT SQL in `PostgresPipeline.process_item` (lines 135-173) with:

```python
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
```

- [ ] **Step 3: Run existing pipeline tests**

```bash
python -m pytest tests/test_pipelines.py -v -k "not test_metrics_refresh and not test_postgres_pipeline"
```

Expected: All cleaning and geocoding tests PASS.

- [ ] **Step 4: Commit**

```bash
git add crawler/heimdall_crawler/pipelines.py
git commit -m "feat: update GeocodingPipeline to skip when enriched, add county columns to PostgresPipeline"
```

---

## Task 6: Rewrite MetricsRefreshPipeline for `region_metrics`

**Files:**
- Modify: `crawler/heimdall_crawler/pipelines.py`
- Create: `tests/test_region_metrics.py`

- [ ] **Step 1: Write failing test**

Create `tests/test_region_metrics.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

```bash
python -m pytest tests/test_region_metrics.py -v
```

Expected: FAIL — `region_metrics` table insert logic doesn't exist yet.

- [ ] **Step 3: Rewrite MetricsRefreshPipeline**

Replace the entire `MetricsRefreshPipeline` class (lines 184-237) in `crawler/heimdall_crawler/pipelines.py`:

```python
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
```

- [ ] **Step 4: Run tests**

```bash
python -m pytest tests/test_region_metrics.py -v
```

Expected: PASS.

- [ ] **Step 5: Update the old metrics test**

In `tests/test_pipelines.py`, update `test_metrics_refresh_computes_ratios` (lines 207-246) to query `region_metrics` instead of `zip_metrics`:

Replace lines 131 and 235-243:
- Line 131: change `from backend.app.models import Base, Listing, ZipMetrics` to `from backend.app.models import Base, Listing, RegionMetrics`
- Line 235: change `result = session.query(ZipMetrics).filter_by(postal_code=zip_code).first()` to:
  ```python
  result = session.execute(
      text("SELECT * FROM region_metrics WHERE level = 'zip' AND code = :code"),
      {"code": zip_code}
  ).mappings().first()
  ```
- Lines 243-244: change cleanup to:
  ```python
  session.execute(text("DELETE FROM region_metrics WHERE code = :code"), {"code": zip_code})
  session.execute(text("DELETE FROM listings WHERE postal_code = :zip"), {"zip": zip_code})
  ```

- [ ] **Step 6: Run all pipeline tests**

```bash
python -m pytest tests/test_pipelines.py tests/test_region_metrics.py -v
```

Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add crawler/heimdall_crawler/pipelines.py tests/test_region_metrics.py tests/test_pipelines.py
git commit -m "feat: rewrite MetricsRefreshPipeline for multi-level region_metrics"
```

---

## Task 7: Backend API — Update `/api/metrics`

**Files:**
- Modify: `backend/app/schemas.py`
- Modify: `backend/app/api/metrics.py`

- [ ] **Step 1: Update MetricPoint schema**

Replace `MetricPoint` in `backend/app/schemas.py` (lines 27-33):

```python
class MetricPoint(BaseModel):
    level: str
    code: str
    name: str
    lat: float | None
    lng: float | None
    value: float | None
    region: str
    listing_count: int
```

- [ ] **Step 2: Rewrite metrics endpoint**

Replace entire contents of `backend/app/api/metrics.py`:

```python
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
```

- [ ] **Step 3: Verify API starts**

```bash
cd /Users/yourstruly/Documents/heimdall
source backend/.venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000 &
sleep 2
curl -s "http://localhost:8000/api/metrics?level=state" | python -m json.tool | head -20
kill %1
```

Expected: JSON array (may be empty if crawler hasn't run yet with new pipeline).

- [ ] **Step 4: Commit**

```bash
git add backend/app/schemas.py backend/app/api/metrics.py
git commit -m "feat: update /api/metrics endpoint to query region_metrics with level param"
```

---

## Task 8: Frontend — Update Metrics Composable and Aggregate Utils

**Files:**
- Modify: `frontend/utils/aggregate.ts`
- Modify: `frontend/composables/useMetrics.ts`

- [ ] **Step 1: Rewrite aggregate.ts**

Replace entire contents of `frontend/utils/aggregate.ts`:

```typescript
/**
 * Converts pre-aggregated MetricPoint data from the API
 * into a Map keyed by code for choropleth rendering.
 */

export interface MetricPoint {
  level: string
  code: string
  name: string
  lat: number | null
  lng: number | null
  value: number | null
  region: string
  listing_count: number
}

export interface AggregatedMetric {
  key: string
  name: string
  value: number
  totalListings: number
}

export function aggregateByCode(points: MetricPoint[]): Map<string, AggregatedMetric> {
  const result = new Map<string, AggregatedMetric>()

  for (const p of points) {
    if (p.value == null || p.listing_count === 0) continue
    result.set(p.code.toUpperCase(), {
      key: p.code,
      name: p.name,
      value: p.value,
      totalListings: p.listing_count,
    })
  }

  return result
}
```

- [ ] **Step 2: Update useMetrics.ts**

Replace entire contents of `frontend/composables/useMetrics.ts`:

```typescript
/**
 * Fetches /api/metrics for a given metric name and geographic level.
 * Caches results per metric+level to avoid redundant API calls.
 */

import type { MetricPoint } from '~/utils/aggregate'

type MetricName = 'rent_to_price_ratio' | 'avg_buy_price_per_sqft' | 'avg_rent_per_sqft'
type GeoLevel = 'state' | 'county' | 'city' | 'zip'

const METRIC_LABELS: Record<MetricName, string> = {
  rent_to_price_ratio: 'Rent/Price Ratio',
  avg_buy_price_per_sqft: 'Buy',
  avg_rent_per_sqft: 'Rent',
}

export function useMetrics() {
  const currentMetric = ref<MetricName>('rent_to_price_ratio')
  const currentLevel = ref<GeoLevel>('state')
  const metrics = ref<MetricPoint[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)
  const cache = new Map<string, MetricPoint[]>()

  async function fetchMetrics(metric: MetricName, level: GeoLevel = 'state') {
    const cacheKey = `${metric}:${level}`
    if (cache.has(cacheKey)) {
      metrics.value = cache.get(cacheKey)!
      currentMetric.value = metric
      currentLevel.value = level
      return
    }

    loading.value = true
    error.value = null
    try {
      const data = await $fetch<MetricPoint[]>('/api/metrics', {
        params: { metric, level },
      })
      cache.set(cacheKey, data)
      metrics.value = data
      currentMetric.value = metric
      currentLevel.value = level
    } catch (e: any) {
      error.value = e.message ?? 'Failed to fetch metrics'
      metrics.value = []
    } finally {
      loading.value = false
    }
  }

  async function switchMetric(metric: MetricName) {
    await fetchMetrics(metric, currentLevel.value)
  }

  async function switchLevel(level: GeoLevel) {
    await fetchMetrics(currentMetric.value, level)
  }

  const metricLabel = computed(() => METRIC_LABELS[currentMetric.value])

  return {
    currentMetric: readonly(currentMetric),
    currentLevel: readonly(currentLevel),
    metrics: readonly(metrics),
    loading: readonly(loading),
    error: readonly(error),
    metricLabel,
    switchMetric,
    switchLevel,
    fetchMetrics,
  }
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/utils/aggregate.ts frontend/composables/useMetrics.ts
git commit -m "feat: update useMetrics and aggregate utils for level-based metrics"
```

---

## Task 9: Frontend — Update ChoroplethMap and Server Proxy

**Files:**
- Modify: `frontend/components/ChoroplethMap.vue`
- Modify: `frontend/server/api/metrics.get.ts`
- Modify: `frontend/pages/index.vue`

- [ ] **Step 1: Update server proxy to forward `level` param**

Replace `frontend/server/api/metrics.get.ts`:

```typescript
export default defineEventHandler(async (event) => {
  const config = useRuntimeConfig()
  const query = getQuery(event)
  const params = new URLSearchParams()

  if (query.metric) params.set('metric', String(query.metric))
  if (query.level) params.set('level', String(query.level))
  if (query.region) params.set('region', String(query.region))

  const url = `${config.apiBase}/api/metrics?${params.toString()}`
  return await $fetch(url)
})
```

- [ ] **Step 2: Update ChoroplethMap.vue**

Replace the `<script setup>` section of `frontend/components/ChoroplethMap.vue`:

```vue
<script setup lang="ts">
import L from 'leaflet'
import { valueToColor, computeBounds } from '~/utils/colorScale'
import { aggregateByCode, type AggregatedMetric, type MetricPoint } from '~/utils/aggregate'

const props = defineProps<{
  metrics: MetricPoint[]
  metricLabel: string
}>()

const emit = defineEmits<{
  boundsChange: [bounds: { min: number; max: number }]
  levelChange: [level: 'state' | 'county']
}>()

const { convert, unitLabel } = useUnits()

const mapContainer = ref<HTMLDivElement | null>(null)
let map: L.Map | null = null
let stateLayer: L.GeoJSON | null = null
let countyLayer: L.GeoJSON | null = null
let statesGeoJson: any = null
let countiesGeoJson: any = null
let currentZoomLevel: 'state' | 'county' = 'state'

const ZOOM_THRESHOLD = 7
const TILE_URL = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png'
const TILE_ATTRIBUTION = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'

async function loadGeoData() {
  try {
    const [states, counties] = await Promise.all([
      fetch('/geo/us-states.json').then(r => r.json()).catch(() => null),
      fetch('/geo/us-counties.json').then(r => r.json()).catch(() => null),
    ])
    statesGeoJson = states
    countiesGeoJson = counties
  } catch (e) {
    console.error('Failed to load GeoJSON:', e)
  }
}

function createPopupContent(name: string, data: AggregatedMetric | undefined): string {
  if (!data) {
    return `
      <div class="map-popup">
        <div class="popup-title">${name}</div>
        <div class="popup-body">No data available</div>
      </div>
    `
  }
  return `
    <div class="map-popup">
      <div class="popup-title">${data.name || name}</div>
      <div class="popup-body">
        Value: <span class="popup-value">${data.value.toFixed(4)}</span><br>
        Listings: <span>${data.totalListings.toLocaleString()}</span>
      </div>
    </div>
  `
}

function styleFeature(
  feature: any,
  aggregated: Map<string, AggregatedMetric>,
  keyProp: string,
  bounds: { min: number; max: number },
) {
  const key = feature.properties?.[keyProp]
  const data = key ? aggregated.get(key.toUpperCase?.() ?? key) : undefined

  return {
    fillColor: data ? valueToColor(data.value, bounds.min, bounds.max) : '#161b22',
    fillOpacity: data ? 0.7 : 0.3,
    color: '#30363d',
    weight: 0.8,
  }
}

function addInteraction(layer: L.Layer, feature: any, aggregated: Map<string, AggregatedMetric>, keyProp: string) {
  const key = feature.properties?.[keyProp]
  const name = feature.properties?.name ?? feature.properties?.NAME ?? key ?? 'Unknown'
  const data = key ? aggregated.get(key.toUpperCase?.() ?? key) : undefined

  layer.on('mouseover', (e: any) => {
    e.target.setStyle({ weight: 2, color: '#58a6ff' })
    e.target.bringToFront()
  })

  layer.on('mouseout', (e: any) => {
    e.target.setStyle({ weight: 0.8, color: '#30363d' })
  })

  layer.bindPopup(createPopupContent(name, data))
}

function renderStateLayer() {
  if (!map || !statesGeoJson) return

  const aggregated = aggregateByCode(props.metrics)
  const values = Array.from(aggregated.values()).map(a => a.value)
  const bounds = computeBounds(values)
  emit('boundsChange', bounds)

  if (stateLayer) {
    map.removeLayer(stateLayer)
  }

  stateLayer = L.geoJSON(statesGeoJson, {
    style: (feature) => styleFeature(feature, aggregated, 'STUSPS', bounds),
    onEachFeature: (feature, layer) => addInteraction(layer, feature, aggregated, 'STUSPS'),
  }).addTo(map)
}

function renderCountyLayer() {
  if (!map || !countiesGeoJson) return

  const aggregated = aggregateByCode(props.metrics)
  const values = Array.from(aggregated.values()).map(a => a.value)
  const bounds = computeBounds(values)
  emit('boundsChange', bounds)

  if (countyLayer) {
    map.removeLayer(countyLayer)
  }

  countyLayer = L.geoJSON(countiesGeoJson, {
    style: (feature) => styleFeature(feature, aggregated, 'GEOID', bounds),
    onEachFeature: (feature, layer) => addInteraction(layer, feature, aggregated, 'GEOID'),
  }).addTo(map)
}

function updateLayers() {
  if (!map) return
  const zoom = map.getZoom()
  const newLevel = zoom < ZOOM_THRESHOLD ? 'state' : 'county'

  if (newLevel !== currentZoomLevel) {
    currentZoomLevel = newLevel
    emit('levelChange', newLevel)
    return // Parent will fetch new data, which triggers the metrics watcher
  }

  if (zoom < ZOOM_THRESHOLD) {
    if (countyLayer) {
      map.removeLayer(countyLayer)
      countyLayer = null
    }
    renderStateLayer()
  } else {
    if (stateLayer) {
      map.removeLayer(stateLayer)
      stateLayer = null
    }
    renderCountyLayer()
  }
}

onMounted(async () => {
  if (!mapContainer.value) return

  await loadGeoData()

  map = L.map(mapContainer.value, {
    center: [39.8, -98.5],
    zoom: 4,
    zoomControl: false,
    attributionControl: false,
  })

  L.tileLayer(TILE_URL, { attribution: TILE_ATTRIBUTION }).addTo(map)

  L.control.zoom({ position: 'topright' }).addTo(map)
  L.control.attribution({ position: 'bottomright' }).addTo(map)

  map.on('zoomend', updateLayers)

  updateLayers()
})

watch(() => props.metrics, () => {
  if (!map) return
  const zoom = map.getZoom()
  if (zoom < ZOOM_THRESHOLD) {
    if (countyLayer) { map.removeLayer(countyLayer); countyLayer = null }
    renderStateLayer()
  } else {
    if (stateLayer) { map.removeLayer(stateLayer); stateLayer = null }
    renderCountyLayer()
  }
}, { deep: true })

onUnmounted(() => {
  if (map) {
    map.remove()
    map = null
  }
})
</script>
```

The `<template>` and `<style>` sections remain unchanged.

- [ ] **Step 3: Update index.vue to wire up level changes**

Replace `frontend/pages/index.vue` `<script setup>` section:

```vue
<script setup lang="ts">
const { currentMetric, metrics, loading: metricsLoading, metricLabel, switchMetric, switchLevel, fetchMetrics } = useMetrics()
const { results, loading: searchLoading, search } = useSearch()

const mapBounds = ref({ min: 0, max: 0 })

onMounted(() => {
  fetchMetrics('rent_to_price_ratio', 'state')
})

function onMetricChange(metric: string) {
  switchMetric(metric as any)
}

function onBoundsChange(bounds: { min: number; max: number }) {
  mapBounds.value = bounds
}

function onLevelChange(level: 'state' | 'county') {
  switchLevel(level)
}
</script>
```

Update the template to pass the new event:

```vue
          <ChoroplethMap
            :metrics="metrics"
            :metric-label="metricLabel"
            @bounds-change="onBoundsChange"
            @level-change="onLevelChange"
          />
```

- [ ] **Step 4: Verify frontend builds**

```bash
cd /Users/yourstruly/Documents/heimdall/frontend
npm run build
```

Expected: Build succeeds without errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/components/ChoroplethMap.vue frontend/server/api/metrics.get.ts frontend/pages/index.vue frontend/utils/aggregate.ts frontend/composables/useMetrics.ts
git commit -m "feat: update frontend for level-based choropleth rendering"
```

---

## Task 10: End-to-End Verification

- [ ] **Step 1: Clear old Numbeo data and re-crawl**

```bash
PGPASSWORD=heimdall psql -h localhost -p 5433 -U heimdall -d heimdall -c "DELETE FROM region_metrics; DELETE FROM listings;"
```

- [ ] **Step 2: Run Numbeo spider**

```bash
cd /Users/yourstruly/Documents/heimdall/crawler
source .venv/bin/activate
scrapy crawl numbeo
```

Expected: ~27 buy + ~27 rent listings crawled, enriched with ZIP/county/coords, and region_metrics populated at all levels.

- [ ] **Step 3: Verify region_metrics populated**

```bash
PGPASSWORD=heimdall psql -h localhost -p 5433 -U heimdall -d heimdall -c "SELECT level, COUNT(*) FROM region_metrics GROUP BY level ORDER BY level;"
```

Expected: Rows at state, city, zip levels (county may be sparse depending on enrichment matches).

- [ ] **Step 4: Verify API returns data**

```bash
curl -s "http://localhost:8000/api/metrics?level=state" | python -m json.tool | head -30
```

Expected: JSON array with state-level metric points containing real values.

- [ ] **Step 5: Verify frontend renders choropleth**

Open `http://localhost:3000` in browser. States on the map should now show colored choropleth fills instead of "No data".

- [ ] **Step 6: Final commit**

```bash
git add -A
git status  # verify no sensitive files
git commit -m "feat: pipeline enrichment complete — choropleth map renders real data"
```
