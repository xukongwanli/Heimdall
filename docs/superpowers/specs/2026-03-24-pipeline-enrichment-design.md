# Pipeline Enrichment & Geo Reference Database

**Date:** 2026-03-24
**Status:** Approved

## Problem

The crawler pipeline produces listings with incomplete geographic data. Numbeo (the only working data source) yields city + state but no ZIP codes, no coordinates, and no county info. This causes:

1. `zip_metrics` table stays empty — the `MetricsRefreshPipeline` groups by `postal_code`, and none exist
2. Choropleth map shows "No data" everywhere — the `/api/metrics` endpoint reads from the empty `zip_metrics`
3. Geocoding fails — Nominatim can't resolve synthetic addresses like "austin city centre average"

## Solution

Three coordinated changes:

1. **`geo_reference` table** — a persistent lookup of US geographic entities at four levels (state, county, city, ZIP), populated from Census Bureau gazetteer files
2. **`EnrichmentPipeline`** — a new pipeline stage that fills missing fields (ZIP, city, county, state, lat/lng, land area) by querying `geo_reference` using whatever fields are available
3. **`region_metrics` table** — replaces `zip_metrics` with multi-level aggregation (state, county, city, ZIP), so the choropleth map gets real data at every zoom level

---

## 1. `geo_reference` Table

### Schema

```sql
CREATE TABLE geo_reference (
    id              SERIAL PRIMARY KEY,
    level           VARCHAR(10) NOT NULL,   -- 'state', 'county', 'city', 'zip'
    code            TEXT NOT NULL,           -- identifier at each level
    name            TEXT NOT NULL,           -- display name
    state_code      VARCHAR(2),             -- state abbreviation (always filled)
    state_fips      VARCHAR(2),             -- state FIPS code
    county_fips     VARCHAR(5),             -- full 5-digit county FIPS
    county_name     TEXT,                   -- county display name
    city            TEXT,                   -- city name (lowercase)
    postal_code     TEXT,                   -- ZIP code (level='zip' only)
    lat             NUMERIC,
    lng             NUMERIC,
    geog            GEOGRAPHY(POINT, 4326),-- for nearest-neighbor spatial queries
    land_area_sqft  NUMERIC,               -- land area in square feet
    water_area_sqft NUMERIC,
    UNIQUE(level, code)
);
```

### Code column conventions

| Level  | `code` value             | Example       |
|--------|--------------------------|---------------|
| state  | State abbreviation       | `TX`          |
| county | 5-digit county FIPS      | `48453`       |
| city   | `{city_slug}-{state}`    | `austin-tx`   |
| zip    | 5-digit ZIP code         | `78701`       |

### City slug convention

The `code` for city-level rows is `{city_slug}-{state_lower}`, where `city_slug` is the city name lowercased with spaces replaced by hyphens and periods/special characters removed. Examples: `austin-tx`, `st-louis-mo`, `new-york-ny`, `winston-salem-nc`.

### Indexes

- `UNIQUE(level, code)` — primary lookup
- `(level, state_code)` — filter by state within a level
- `(level, city, state_code)` — city+state enrichment lookup
- PostGIS `GEOGRAPHY` column `geog` with GIST index — for nearest-neighbor queries (step 5 of enrichment). The `lat`/`lng` NUMERIC columns are kept for convenience, but spatial queries use the `geog` column via `ST_DWithin` / `ST_Distance`

### Data sources

Four Census Bureau gazetteer files (TSV, publicly available, ~5MB total):

- `2024_Gaz_state_national.txt` → ~52 state rows
- `2024_Gaz_counties_national.txt` → ~3,200 county rows
- `2024_Gaz_place_national.txt` → ~30,000 city/place rows
- `2024_Gaz_zcta_national.txt` → ~33,000 ZIP rows

### Population script

`scripts/populate_geo_reference.py`:
1. Downloads all four gazetteer files from census.gov
2. Parses TSV format, normalizes field names
3. Converts land/water area from square miles to square feet
4. Bulk-inserts into `geo_reference` with ON CONFLICT upsert
5. Idempotent — safe to re-run when Census data updates

---

## 2. `region_metrics` Table (replaces `zip_metrics`)

### Schema

```sql
CREATE TABLE region_metrics (
    level                   VARCHAR(10) NOT NULL,  -- 'state', 'county', 'city', 'zip'
    code                    TEXT NOT NULL,          -- same code as geo_reference
    name                    TEXT NOT NULL,          -- display name
    country                 VARCHAR(2) NOT NULL DEFAULT 'US',
    region                  TEXT NOT NULL,          -- state abbreviation
    lat                     NUMERIC,
    lng                     NUMERIC,
    avg_buy_price_per_sqft  NUMERIC,
    avg_rent_per_sqft       NUMERIC,
    rent_to_price_ratio     NUMERIC,
    listing_count           INTEGER NOT NULL DEFAULT 0,
    updated_at              TIMESTAMP WITH TIME ZONE NOT NULL,
    PRIMARY KEY (level, code)
);
```

### Aggregation logic

`MetricsRefreshPipeline` aggregates listings into four levels on spider close:

```
GROUP BY region                    → level='state',  code=region
GROUP BY county_fips               → level='county', code=county_fips
GROUP BY city, region              → level='city',   code='{city}-{region}'
GROUP BY postal_code               → level='zip',    code=postal_code
```

Each level computes:
- `avg_buy_price_per_sqft` — average of buy listings' `price_per_sqft`
- `avg_rent_per_sqft` — average of rent listings' `price_per_sqft`
- `rent_to_price_ratio` — `(avg_rent * 12) / avg_buy`
- `listing_count` — total listings in group
- `lat`, `lng` — extracted from the PostGIS `coordinates` column via `ST_Y`/`ST_X` (averaged), falling back to `geo_reference` lat/lng via a LEFT JOIN when coordinates are NULL
- `name` — looked up from `geo_reference` via JOIN on `(level, code)`. For ZIP-level rows, this is the city name associated with that ZIP (e.g., "Austin 78701")

### Handling empty postal codes

Listings where enrichment finds no match and `postal_code` remains empty are:
- Included in state-level and city-level aggregation (they still have `region` and `city`)
- Excluded from ZIP-level aggregation (the query filters `WHERE postal_code != ''`)
- The `PostgresPipeline` inserts them with `postal_code=''` (not NULL), which is valid per the schema

---

## 3. Enrichment Pipeline

### Position in pipeline chain

```
CleaningPipeline       (100)
EnrichmentPipeline     (150)  ← NEW
GeocodingPipeline      (200)
PostgresPipeline       (300)
MetricsRefreshPipeline (400)
```

### Enrichment strategy

Adaptive lookup — uses whatever fields are available to fill what's missing:

```
1. Has postal_code?     → lookup level='zip'    → fill city, county, state, lat/lng, land_area
2. Has city + state?    → lookup level='city'   → fill primary ZIP, county, lat/lng, land_area
3. Has county + state?  → lookup level='county' → fill lat/lng, land_area
4. Has state only?      → lookup level='state'  → fill lat/lng, land_area
5. Has lat + lng?       → nearest-neighbor query → fill everything from closest match
```

Rules:
- Never overwrites data the spider already provided
- **All steps run in sequence** — each step only fills fields that are still None/empty, so a less-specific step can fill gaps left by a more-specific one
- In-memory cache keyed by `(level, code)` to avoid repeated DB queries

### Field name convention

The enrichment pipeline writes to `item["latitude"]` and `item["longitude"]` (matching existing `ListingItem` field names and `GeocodingPipeline` conventions), **not** `lat`/`lng`.

### Land area

The enrichment pipeline does **not** persist `land_area_sqft` to the `listings` table — it lives only in `geo_reference` for future use (e.g., density calculations). The enrichment focuses on filling geographic identity fields (ZIP, city, county, state, lat/lng) needed for aggregation.

### Known limitation: city → ZIP assignment

When enrichment assigns a ZIP code to a city-level listing (e.g., Numbeo's "Austin, TX"), it picks the single ZIP with the largest population for that city. This means all Numbeo listings for Austin get ZIP `78701`. ZIP-level aggregation for these cities will be identical to city-level. This is acceptable because:
- Real listing spiders (Zillow, Realtor, Redfin) will provide actual per-listing ZIP codes when unblocked
- The choropleth map primarily uses state and county zoom levels, where this is not an issue

### DB connection lifecycle

`EnrichmentPipeline` follows the same `open_spider`/`close_spider` pattern as `PostgresPipeline` — creates an engine and sessionmaker in `open_spider`, disposes in `close_spider`.

### Impact on GeocodingPipeline

After enrichment fills `item["latitude"]`/`item["longitude"]` from the reference table, `GeocodingPipeline` becomes a fallback. It checks whether latitude/longitude are already set and skips Nominatim if so. This fixes the Numbeo problem entirely.

---

## 4. End-to-End Data Flow

```
Spider (e.g. Numbeo)
  yields: city="austin", region="TX", postal_code="", lat/lng=None

CleaningPipeline (100)
  normalizes address, parses price/sqft, calculates price_per_sqft

EnrichmentPipeline (150)
  has city+state, no ZIP
  queries geo_reference WHERE level='city' AND city='austin' AND state_code='TX'
  fills: postal_code="78701", county_fips="48453", county_name="Travis County"
         lat=30.267, lng=-97.743

GeocodingPipeline (200)
  lat/lng already filled → skips Nominatim

PostgresPipeline (300)
  upserts listing with all enriched fields

MetricsRefreshPipeline (400)
  on spider close, aggregates into region_metrics at 4 levels
```

Frontend result:
- `GET /api/metrics?level=state` → returns states with real metric values
- Zoom in → `GET /api/metrics?level=county` → county-level detail
- Choropleth map renders colored regions instead of "No data"

---

## 5. API Changes

### `GET /api/metrics`

New query parameter:

| Param  | Type   | Default | Values                          |
|--------|--------|---------|---------------------------------|
| level  | string | state   | `state`, `county`, `city`, `zip`|
| metric | string | rent_to_price_ratio | unchanged                |
| region | string | null    | unchanged (state filter)        |

Response schema change (`MetricPoint`):

```python
class MetricPoint(BaseModel):
    level: str            # NEW
    code: str             # NEW (replaces postal_code)
    name: str             # NEW
    lat: float | None
    lng: float | None
    value: float | None
    region: str
    listing_count: int
```

---

## 6. Frontend Changes

### `ChoroplethMap.vue`
- Zoom < 7: fetches `?level=state`, keys features by `STUSPS` matching `code`
- Zoom 7+: fetches `?level=county`, keys features by `GEOID` matching `code`
- Data arrives pre-aggregated — no client-side aggregation needed
- On zoom crossing the threshold (7), calls `switchMetric` with the new level to trigger a re-fetch

### `useMetrics.ts`
- `fetchMetrics()` accepts `level` parameter
- Cache key includes level: `${metric}:${level}`
- When `ChoroplethMap` crosses the zoom threshold, it calls `fetchMetrics` with the new level, which either hits the cache or makes a new API call

### `aggregate.ts`
- Update `MetricPoint` TypeScript interface to match new API shape: replace `postal_code` with `code`, add `level` and `name` fields
- Simplify `aggregateByState` and `aggregateByCounty` into a single `aggregateByCode` function that converts the API response array into a `Map<string, AggregatedMetric>` keyed by `code`, since the backend handles the level-specific aggregation
- Remove the `zipToCounty` dependency entirely

### `metrics.get.ts` (server proxy)
- Forward `level` query param to backend (add to the `query` object alongside existing `metric` and `region` params)

### Breaking change note
This is a breaking change to the `/api/metrics` response shape (`postal_code` → `code`, new `level`/`name` fields). Since the frontend and backend are deployed together and there are no external API consumers, this is acceptable without a versioning strategy.

---

## 7. File Changes

### New files

| File | Purpose |
|------|---------|
| `scripts/populate_geo_reference.py` | Downloads Census gazetteers, loads into `geo_reference` |
| `backend/alembic/versions/*_add_geo_reference_and_region_metrics.py` | Migration: create `geo_reference`, replace `zip_metrics` with `region_metrics`, add columns to `listings` |

### Modified files

| File | Changes |
|------|---------|
| `crawler/heimdall_crawler/pipelines.py` | Add `EnrichmentPipeline` (150), update `GeocodingPipeline` to skip when lat/lng present, update `PostgresPipeline` INSERT to include `county_fips`/`county_name`, rewrite `MetricsRefreshPipeline` for multi-level `region_metrics` |
| `crawler/heimdall_crawler/items.py` | Add `county_fips`, `county_name` fields |
| `crawler/heimdall_crawler/settings.py` | Register `EnrichmentPipeline` at 150 |
| `crawler/requirements.txt` | Add `requests` |
| `backend/app/models.py` | Add `GeoReference` model, replace `ZipMetrics` with `RegionMetrics`, add `county_fips`/`county_name` to `Listing` |
| `backend/app/schemas.py` | Update `MetricPoint` with `level`, `code`, `name` fields |
| `backend/app/api/metrics.py` | Query `RegionMetrics` with `level` param |
| `frontend/composables/useMetrics.ts` | Pass `level` param, update cache key |
| `frontend/components/ChoroplethMap.vue` | Fetch level-specific metrics based on zoom, remove client-side aggregation |
| `frontend/utils/aggregate.ts` | Simplify to Map conversion (backend does aggregation) |
| `frontend/server/api/metrics.get.ts` | Forward `level` param |

### Unchanged

Spider files (`numbeo.py`, `zillow.py`, etc.) — enrichment is transparent to spiders.
