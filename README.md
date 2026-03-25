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
- **Playwright browsers** — installed during crawler setup

## Local Setup

All paths below are relative to the project root (`heimdall/`).

The project has **three separate environments**:

| Component | Directory | Environment | Purpose |
|-----------|-----------|-------------|---------|
| Backend   | `backend/` | Python venv (`backend/.venv`) | FastAPI API server, DB migrations |
| Crawler   | `crawler/` | Python venv (`crawler/.venv`) | Scrapy spiders, data pipelines |
| Frontend  | `frontend/` | Node.js (`frontend/node_modules`) | Nuxt dev server |

### 1. Start the database

```bash
# From: project root (heimdall/)
docker compose up -d
```

This starts PostgreSQL 17 + PostGIS 3.5 on port **5433** with:
- Database: `heimdall`
- User: `heimdall`
- Password: `heimdall`

Verify it's running:

```bash
# From: anywhere
PGPASSWORD=heimdall psql -h localhost -p 5433 -U heimdall -d heimdall -c "SELECT 1"
```

### 2. Set up the backend

```bash
# From: project root (heimdall/)
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Run database migrations (must be inside `backend/` with its venv active):

```bash
# From: backend/
# Venv: backend/.venv
alembic upgrade head
```

Start the API server:

```bash
# From: backend/
# Venv: backend/.venv
uvicorn backend.app.main:app --reload --port 8000
```

The API is now at `http://localhost:8000`. Docs at `http://localhost:8000/docs`.

### 3. Set up the crawler

```bash
# From: project root (heimdall/)
cd crawler
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 4. Populate the geo reference data

This downloads US Census gazetteer files (~5 MB) and loads ~69K geographic reference rows (states, counties, cities, ZIP codes) into the `geo_reference` table. The EnrichmentPipeline uses this data to fill missing fields on crawled listings.

```bash
# From: project root (heimdall/)
# Venv: crawler/.venv (needs requests + sqlalchemy)
source crawler/.venv/bin/activate
pip install requests

# From: project root (heimdall/)
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
# From: project root (heimdall/)
cd frontend
npm install
```

Download GeoJSON boundary files for the choropleth map:

```bash
# From: frontend/
bash scripts/fetch-geo.sh
```

Start the dev server:

```bash
# From: frontend/
npm run dev
```

The frontend is now at `http://localhost:3000`.

### 6. Crawl some data

```bash
# From: project root (heimdall/)
cd crawler
source .venv/bin/activate
scrapy crawl numbeo
```

Or run all spiders:

```bash
# From: crawler/
# Venv: crawler/.venv
python run_all.py
```

After crawling, `region_metrics` is automatically refreshed. The choropleth map at `http://localhost:3000` should now show colored state fills.

## Running Tests

Tests require PostgreSQL running and migrations applied.

```bash
# From: project root (heimdall/)
# Venv: crawler/.venv (has all Python deps needed for tests)
source crawler/.venv/bin/activate
pip install pytest

# Run all tests
python -m pytest tests/ -v

# Run specific test suites
python -m pytest tests/test_enrichment.py -v      # EnrichmentPipeline tests
python -m pytest tests/test_region_metrics.py -v   # MetricsRefreshPipeline tests
python -m pytest tests/test_pipelines.py -v        # Cleaning, geocoding, pipeline tests
```

## Day-to-Day Usage

Once setup is complete, here's what you need to run each time:

```bash
# Terminal 1 — Database (if not already running)
# From: project root (heimdall/)
docker compose up -d

# Terminal 2 — Backend API
# From: backend/
source .venv/bin/activate
uvicorn backend.app.main:app --reload --port 8000

# Terminal 3 — Frontend
# From: frontend/
npm run dev

# Terminal 4 — Crawl data (as needed)
# From: crawler/
source .venv/bin/activate
scrapy crawl numbeo
```

## Project Structure

```
heimdall/
  backend/                 # Python venv: backend/.venv
    app/
      api/                 # FastAPI route handlers (listings, metrics, search)
      database.py          # SQLAlchemy engine and session
      main.py              # FastAPI app entry point
      models.py            # ORM models (Listing, GeoReference, RegionMetrics)
      schemas.py           # Pydantic response models
    alembic/               # Database migrations (run from backend/)
    requirements.txt
  crawler/                 # Python venv: crawler/.venv
    heimdall_crawler/
      spiders/             # Scrapy spiders (numbeo, zillow, realtor, redfin)
      items.py             # ListingItem definition
      middlewares.py       # User-agent rotation
      pipelines.py         # Cleaning, Enrichment, Geocoding, Postgres, MetricsRefresh
      settings.py          # Scrapy configuration
    run_all.py             # Run all spiders
    requirements.txt
  frontend/                # Node.js: frontend/node_modules
    components/            # Vue components (ChoroplethMap, SearchBar, ResultsTable, etc.)
    composables/           # Vue composables (useMetrics, useSearch, useUnits)
    pages/                 # Nuxt pages (index.vue)
    server/api/            # Server proxy routes to FastAPI
    utils/                 # Color scale, metric aggregation
    public/geo/            # GeoJSON boundary files (gitignored, fetched by script)
    scripts/fetch-geo.sh   # Download GeoJSON boundary files
    nuxt.config.ts
    package.json
  scripts/
    populate_geo_reference.py  # Load Census gazetteer data (run with crawler venv)
  tests/                   # pytest test suite (run with crawler venv from project root)
  docker-compose.yml       # PostgreSQL + PostGIS
```
