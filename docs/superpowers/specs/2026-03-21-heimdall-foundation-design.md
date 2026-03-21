# Heimdall Foundation Design

## Overview

Heimdall is a global real estate data aggregation platform. This spec covers the **v1 foundation scoped to the US market**, with schema designed to support international expansion later. It crawls public listing data from Zillow, Realtor.com, and Redfin, stores it in PostgreSQL, and serves it through a Vue web frontend. Users can search by city/state and view a ZIP-code-level heatmap of key metrics including rent-to-price ratio.

## Data Model

### `listings` table

| Column | Type | Notes |
|--------|------|-------|
| id | UUID | PK |
| source | enum (zillow, realtor, redfin) | Extensible for future sources |
| listing_type | enum (buy, rent) | |
| address | text | Normalized (see Address Normalization) |
| city | text | |
| country | char(2) | ISO 3166-1 alpha-2, default 'US' for v1 |
| region | text | State for US (2-letter), adaptable internationally |
| postal_code | text | ZIP for US, flexible for international |
| price | numeric | Sale price or monthly rent |
| sqft | numeric | Nullable; listings without sqft are stored but excluded from per-sqft calculations |
| price_per_sqft | numeric | Populated by pipeline: price / sqft, NULL when sqft is NULL or 0 |
| coordinates | PostGIS geometry point | For heatmap |
| source_url | text | |
| published_at | timestamp | From source; falls back to `crawled_at` if source doesn't provide it |
| crawled_at | timestamp | |

- Unique constraint on `(source, address, listing_type)` — dedup is per-source to avoid fragile cross-source address matching in v1
- On conflict, upsert only if incoming `published_at` is newer
- Indexes on `country`, `region`, `city`, `postal_code`, `listing_type`, spatial index on `coordinates`

### Address Normalization Rules

The `CleaningPipeline` normalizes addresses before storage:
- Lowercase and trim whitespace
- Expand abbreviations: St -> Street, Ave -> Avenue, Apt -> Apartment, etc.
- Remove unit/suite punctuation variations (#4 -> Apartment 4)
- Strip trailing city/state/zip (these go in separate columns)

Cross-source dedup is deferred to a future version with more sophisticated address matching.

### `zip_metrics` table

| Column | Type | Notes |
|--------|------|-------|
| postal_code | text | PK (ZIP code for US) |
| country | char(2) | Default 'US' |
| region | text | State for US |
| lat | numeric | ZIP centroid, computed as AVG of listing coordinates |
| lng | numeric | ZIP centroid, computed as AVG of listing coordinates |
| avg_buy_price_per_sqft | numeric | NULL if no buy listings with sqft in this ZIP |
| avg_rent_per_sqft | numeric | NULL if no rent listings with sqft in this ZIP |
| rent_to_price_ratio | numeric | NULL if either buy or rent data is missing |
| listing_count | integer | |
| updated_at | timestamp | |

**Rent-to-price ratio formula:** `(avg_rent_per_sqft * 12) / avg_buy_price_per_sqft` — annualized rent per sqft divided by buy price per sqft. NULL when a ZIP lacks either buy or rent listings with valid sqft data.

Refreshed via full recompute after each crawl run. Acceptable at current scale; switch to materialized view with `REFRESH MATERIALIZED VIEW CONCURRENTLY` if performance becomes an issue.

## Crawler Architecture

Scrapy project with one spider per source:

- `ZillowSpider` — scrapes Zillow public listing pages
- `RealtorSpider` — scrapes Realtor.com listings
- `RedfinSpider` — scrapes Redfin listings

### Shared Pipeline

1. `CleaningPipeline` — normalizes addresses (see Address Normalization Rules), extracts city/region/postal_code, converts price strings to numbers, computes `price_per_sqft` (NULL if sqft missing/zero)
2. `GeocodingPipeline` — converts addresses to lat/lng via Nominatim (free, max 1 req/sec). Skips geocoding for addresses already in the DB with coordinates. Caches results to minimize API calls.
3. `PostgresPipeline` — upserts into `listings`; on (source, address, listing_type) conflict, keeps row with newer `published_at`
4. `MetricsRefreshPipeline` — refreshes `zip_metrics` aggregates after crawl completes

### Anti-Bot Middleware

- Rotating User-Agent strings
- Random request delays via Scrapy AUTOTHROTTLE
- Retry with backoff on 403/429
- Integration point for proxy rotation (not needed for local testing)
- **CAPTCHA handling:** Scrapy middleware with integration point for headless browser rendering (Playwright) for JavaScript-heavy pages. For v1 local testing, spiders will target listing index/search result pages that typically don't trigger CAPTCHA. Full CAPTCHA-solving service integration (e.g., 2Captcha) is deferred but the middleware architecture supports plugging it in.

### Error Handling

- Spiders log warnings when page structure changes (expected selectors not found) to detect source HTML changes early
- Failed items are logged with URL and error reason for manual review
- Crawl summary printed at end: items scraped, items failed, items upserted

### Manual Trigger

CLI command per spider (`scrapy crawl zillow`) or `run_all.py` to run all spiders sequentially.

## Backend API

FastAPI with SQLAlchemy async + asyncpg.

### Endpoints

**`GET /api/listings`** — query listings with filters
- Query params: `region`, `city`, `postal_code`, `listing_type`
- Returns listings sorted by `price_per_sqft` (nulls last), paginated (limit/offset)

**`GET /api/metrics`** — ZIP-level aggregates for heatmap
- Query params: `region` (optional), `metric` (rent_to_price_ratio | avg_buy_price_per_sqft | avg_rent_per_sqft)
- Returns array of `{postal_code, lat, lng, value}` — lat/lng from `zip_metrics` table

**`GET /api/search`** — search by city or state name
- Query param: `q` (text)
- Returns matching cities/states with aggregate metrics

CORS enabled for local Vue dev server.

## Frontend

Vue 3 + Nuxt with two views.

### Search View (`/`)

- Search bar at top — type city or state name, hits `/api/search`
- Results show region summary: avg price/sqft, avg rent/sqft, rent-to-price ratio
- Sortable table of individual listings ordered by price per sqft
- Pagination

### Map View (`/map`)

- Full-screen Leaflet map with heatmap overlay via `leaflet.heat`
- Dropdown to select metric: rent-to-price ratio, price/sqft (buy), rent/sqft
- Color scale: red = high, green/blue = low
- Data from `/api/metrics`
- Click ZIP region to see aggregate stats in popup

### Shared

- Nav bar to switch between Search and Map
- Minimal functional styling

## Project Structure

```
heimdall/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   │   ├── listings.py
│   │   │   ├── metrics.py
│   │   │   └── search.py
│   │   ├── models.py
│   │   ├── database.py
│   │   └── schemas.py
│   ├── alembic/
│   ├── requirements.txt
│   └── alembic.ini
├── crawler/
│   ├── scrapy.cfg
│   ├── heimdall_crawler/
│   │   ├── spiders/
│   │   │   ├── zillow.py
│   │   │   ├── realtor.py
│   │   │   └── redfin.py
│   │   ├── pipelines.py
│   │   ├── middlewares.py
│   │   ├── items.py
│   │   └── settings.py
│   ├── run_all.py
│   └── requirements.txt
├── frontend/
│   ├── nuxt.config.ts
│   ├── pages/
│   │   ├── index.vue
│   │   └── map.vue
│   ├── components/
│   │   ├── ListingTable.vue
│   │   ├── SearchBar.vue
│   │   └── HeatMap.vue
│   └── package.json
├── docker-compose.yml
└── CLAUDE.md
```

## Local Dev Workflow

1. `docker-compose up -d` — starts PostgreSQL with PostGIS
2. `alembic upgrade head` — runs migrations
3. `python run_all.py` — triggers crawlers manually
4. `uvicorn app.main:app --reload` — starts API server
5. `npm run dev` (in frontend/) — starts Vue dev server

## Decisions and Constraints

- **US-only for v1** — schema uses `country`, `region`, `postal_code` to support future international expansion
- No photos at this stage
- **Dedup is per-source** — unique on `(source, address, listing_type)`, cross-source dedup deferred
- **`published_at` fallback** — uses `crawled_at` when source doesn't provide publication date
- ZIP-code-level granularity for heatmap
- Manual crawler trigger (no scheduler yet)
- 200 GB max storage budget
- ~1-hour refresh cadence (future, not implemented in v1)
- **CAPTCHA solving deferred** — middleware architecture supports it, but v1 targets pages that don't typically require it
