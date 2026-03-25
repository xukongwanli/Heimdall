# Heimdall

Real estate data aggregation platform. Crawls publicly available property data, stores it in PostgreSQL, and serves it through a web interface with choropleth map visualization.

## How It Works

```
Scrapy Spiders  -->  Pipelines  -->  PostgreSQL + PostGIS  <--  FastAPI  <--  Nuxt Frontend
   (crawl)        (clean, enrich,      (listings,              (REST API)     (map, search,
                   geocode, store,      geo_reference,                         metrics)
                   aggregate)           region_metrics)
```

**Crawler layer** — Scrapy spiders scrape listing data from public sources. Items flow through a pipeline chain:

1. **CleaningPipeline** (100) — normalizes addresses, parses prices/sqft, computes price_per_sqft
2. **EnrichmentPipeline** (150) — fills missing geographic fields (city, state, ZIP, county, lat/lng) by looking up a `geo_reference` table populated from US Census gazetteers
3. **GeocodingPipeline** (200) — geocodes addresses via Nominatim when enrichment didn't provide coordinates
4. **PostgresPipeline** (300) — upserts listings into the database with conflict resolution (newer published_at wins)
5. **MetricsRefreshPipeline** (400) — aggregates listings into `region_metrics` at state, county, city, and ZIP levels on spider close

**Backend API** — FastAPI serves three endpoints:

- `GET /api/listings` — paginated listings with filters (region, city, postal_code, listing_type)
- `GET /api/search?q=` — search by city/region name, returns aggregated stats
- `GET /api/metrics?metric=&level=` — pre-aggregated metrics for choropleth rendering (state/county/city/zip)

**Frontend** — Nuxt 4 SPA with a dark theme. Features a search bar, sortable results table, metric toggle (rent/price ratio, buy $/sqft, rent $/sqft), and a Leaflet choropleth map that switches between state and county layers on zoom.

## Prerequisites

- **macOS** (tested on Apple Silicon with Rosetta)
- **Docker Desktop** — for PostgreSQL + PostGIS
- **Python 3.12+**
- **Node.js 18+** and npm
- **Playwright browsers** — for JS-rendered sites (`playwright install chromium`)

## Local Setup

### 1. Start the database

```bash
docker compose up -d
```

This starts PostgreSQL 17 + PostGIS 3.5 on port **5433** with:
- Database: `heimdall`
- User: `heimdall`
- Password: `heimdall`

Verify it's running:

```bash
PGPASSWORD=heimdall psql -h localhost -p 5433 -U heimdall -d heimdall -c "SELECT 1"
```

### 2. Set up the backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run database migrations:

```bash
alembic upgrade head
```

Start the API server:

```bash
uvicorn backend.app.main:app --reload --port 8000
```

The API is now at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### 3. Set up the crawler

```bash
cd crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Populate the geo reference data

This downloads US Census gazetteer files (~5 MB) and loads ~69K geographic reference rows (states, counties, cities, ZIP codes) into the `geo_reference` table. The EnrichmentPipeline uses this data to fill missing fields on crawled listings.

```bash
pip install requests  # if not already installed
python scripts/populate_geo_reference.py
```

Expected output:

```
Downloading and processing Census gazetteer files...
  States: 52 rows
  Counties: ~3200 rows
  Places: ~32000 rows
  ZCTAs: ~33000 rows
Done. Total rows upserted: ~69000
```

### 5. Set up the frontend

```bash
cd frontend
npm install
```

Download GeoJSON boundary files for the choropleth map:

```bash
bash scripts/fetch-geo.sh
```

Start the dev server:

```bash
npm run dev
```

The frontend is now at `http://localhost:3000`.

### 6. Crawl some data

Run the Numbeo spider (the only working public source currently):

```bash
cd crawler
source .venv/bin/activate
scrapy crawl numbeo
```

Or run all spiders:

```bash
python run_all.py
```

After crawling, `region_metrics` is automatically refreshed. The choropleth map at `http://localhost:3000` should now show colored state fills.

## Running Tests

```bash
# From project root, using the crawler venv (has all deps)
source crawler/.venv/bin/activate
pip install pytest

# Run all tests
python -m pytest tests/ -v

# Run specific test suites
python -m pytest tests/test_enrichment.py -v      # EnrichmentPipeline tests
python -m pytest tests/test_region_metrics.py -v   # MetricsRefreshPipeline tests
python -m pytest tests/test_pipelines.py -v        # Cleaning, geocoding, pipeline tests
```

Tests that interact with the database require PostgreSQL to be running and migrations applied.

## Project Structure

```
heimdall/
  backend/
    app/
      api/            # FastAPI route handlers (listings, metrics, search)
      database.py     # SQLAlchemy engine and session
      main.py         # FastAPI app entry point
      models.py       # ORM models (Listing, GeoReference, RegionMetrics)
      schemas.py      # Pydantic response models
    alembic/          # Database migrations
    requirements.txt
  crawler/
    heimdall_crawler/
      spiders/        # Scrapy spiders (numbeo, zillow, realtor, redfin)
      items.py        # ListingItem definition
      middlewares.py   # User-agent rotation
      pipelines.py    # Cleaning, Enrichment, Geocoding, Postgres, MetricsRefresh
      settings.py     # Scrapy configuration
    run_all.py        # Run all spiders
    requirements.txt
  frontend/
    components/       # Vue components (ChoroplethMap, SearchBar, ResultsTable, etc.)
    composables/      # Vue composables (useMetrics, useSearch, useUnits)
    pages/            # Nuxt pages (index.vue)
    server/api/       # Server proxy routes to FastAPI
    utils/            # Color scale, metric aggregation
    public/geo/       # GeoJSON boundary files (gitignored, fetched by script)
    nuxt.config.ts
    package.json
  scripts/
    populate_geo_reference.py  # Load Census gazetteer data
  tests/              # pytest test suite
  docker-compose.yml  # PostgreSQL + PostGIS
```
