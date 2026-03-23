# Heimdall Frontend — Setup & Testing Guide

## Prerequisites

- **Node.js** 20+ (verified with v24.14.0)
- **Python 3.14** with backend virtual environment
- **PostgreSQL 17** with PostGIS running (via `docker-compose up -d`)
- **GDAL** (optional, for GeoJSON conversion from Census shapefiles; fallback exists)

## Project Structure

```
frontend/
├── nuxt.config.ts              # Nuxt config: Leaflet CSS, API proxy, dark theme
├── app.vue                     # Root layout
├── pages/
│   └── index.vue               # Single page: search + results + choropleth map
├── components/
│   ├── NavBar.vue              # Logo, $/sqft ↔ $/m² toggle, nav links
│   ├── SearchBar.vue           # Search input with debounced emission
│   ├── ResultsTable.vue        # Sortable search results table
│   ├── MetricToggle.vue        # Rent/Price | Buy $/sqft | Rent $/sqft buttons
│   ├── MapLegend.vue           # Color gradient legend overlay
│   └── ChoroplethMap.vue       # Leaflet map with GeoJSON choropleth
├── composables/
│   ├── useUnits.ts             # Global sqft/m² toggle, localStorage persistence
│   ├── useMetrics.ts           # Fetches /api/metrics with caching
│   └── useSearch.ts            # Debounced /api/search
├── utils/
│   ├── colorScale.ts           # Value → color mapping (blue→green→orange→red)
│   └── aggregate.ts            # ZIP-level → state/county aggregation
├── assets/styles/main.css      # Dark theme CSS custom properties
├── public/geo/                 # GeoJSON boundary files (downloaded, gitignored)
│   ├── us-states.json          # US state boundaries with STUSPS property
│   ├── us-counties.json        # US county boundaries with GEOID property
│   └── zip-to-county.json      # ZIP→county FIPS lookup (placeholder)
├── server/api/                 # Nuxt server proxy routes → FastAPI
│   ├── metrics.get.ts
│   ├── search.get.ts
│   └── listings.get.ts
└── scripts/
    └── fetch-geo.sh            # Downloads Census TIGER GeoJSON files
```

## Setup

### 1. Download GeoJSON boundary data

```bash
cd frontend
chmod +x scripts/fetch-geo.sh
./scripts/fetch-geo.sh
```

This downloads simplified US state and county boundaries from the Census Bureau into `public/geo/`. If GDAL (`ogr2ogr`) is installed, it converts directly from shapefiles. Otherwise, it falls back to pre-converted GeoJSON and adds the required `STUSPS` property via Python.

Verify the files:
```bash
python3 -c "
import json
states = json.load(open('public/geo/us-states.json'))
counties = json.load(open('public/geo/us-counties.json'))
print(f'States: {len(states[\"features\"])} features')
print(f'Counties: {len(counties[\"features\"])} features')
print(f'State properties: {list(states[\"features\"][0][\"properties\"].keys())}')
"
```

Expected: ~52 state features with `STUSPS` property, ~3200 county features with `GEOID` property.

### 2. Install dependencies

```bash
cd frontend
npm install
```

### 3. Start the backend

In a separate terminal:
```bash
cd /path/to/heimdall
docker-compose up -d          # Start PostgreSQL
cd backend
source .venv/bin/activate     # Activate Python venv
uvicorn backend.app.main:app --reload --port 8000
```

Verify: `curl http://localhost:8000/api/metrics?metric=rent_to_price_ratio` should return JSON.

### 4. Start the frontend

```bash
cd frontend
npx nuxt dev --port 3000
```

Open **http://localhost:3000** in your browser.

## Testing Each Feature

### 1. Page Layout

**What to check:**
- Dark background (`#0d1117`) fills the entire page
- JetBrains Mono monospace font is used throughout
- Three sections visible from top to bottom: nav bar, search area, map

**Expected behavior:**
- Nav bar shows "HEIMDALL" logo in blue (`#58a6ff`) on the left
- Unit toggle ($/sqft | $/m²) and nav links on the right
- "GLOBAL REAL ESTATE INTELLIGENCE" tagline above the search bar
- Search input with placeholder text
- Choropleth map fills the width below the search section

### 2. Unit Toggle ($/sqft ↔ $/m²)

**How to test:**
1. Click the unit toggle button in the nav bar
2. The active unit should highlight green (`#238636`)
3. Search for a city (e.g., type "Austin") and observe the results table
4. Toggle units — the Buy and Rent columns should update their values
5. Refresh the page — the selected unit should persist (stored in localStorage)

**Conversion factor:** $/sqft × 10.764 = $/m²

### 3. Search Bar

**How to test:**
1. Type a city name (e.g., "Austin", "New York", "Miami") in the search bar
2. After 300ms debounce, results should appear in a table between the search bar and the map
3. Results table shows: Location, Buy $/sqft (green), Rent $/sqft (blue), Ratio (orange)
4. Clear the search input — results table should disappear

**Note:** Search requires the backend to have listing data in the database. If the database is empty, search will return no results. You can verify the API directly:
```bash
curl "http://localhost:8000/api/search?q=austin"
```

### 4. Results Table Sorting

**How to test:**
1. Search for a broad term (e.g., a state abbreviation like "TX") to get multiple results
2. Click any column header to sort by that column
3. Click the same header again to reverse the sort order
4. Null values sort to the bottom

### 5. Metric Toggle

**How to test:**
1. Above the map, find the three toggle buttons: Rent/Price, Buy $/sqft, Rent $/sqft
2. Click each button — the active one highlights green
3. The map should recolor based on the selected metric
4. The legend (bottom-left of map) should update its label and value range

**API metric values:**
- Rent/Price → `rent_to_price_ratio`
- Buy $/sqft → `avg_buy_price_per_sqft`
- Rent $/sqft → `avg_rent_per_sqft`

### 6. Choropleth Map

**How to test:**
1. On page load, the map should show the entire US with CartoDB Dark Matter tiles
2. State polygons should be color-filled based on the rent-to-price ratio
3. States with data are colored on a blue→green→orange→red scale
4. States without data appear as dark neutral fill (`#161b22`) at lower opacity

**Color scale:**
| Value | Color |
|-------|-------|
| Low | Blue (`#0a84ff`) |
| Below avg | Green (`#32d74b`) |
| Above avg | Orange (`#ff9f0a`) |
| High | Red (`#ff453a`) |

### 7. Map Hover & Click

**How to test:**
1. Hover over a state polygon — its border should highlight blue (`#58a6ff`) with weight 2
2. Move the mouse away — border returns to default (`#30363d`, weight 0.8)
3. Click a state — a popup appears with:
   - State name in blue
   - Metric value in orange
   - Listing count
4. States without data show "No data available" in the popup

### 8. Map Zoom (Multi-Scale)

**How to test:**
1. At zoom levels 1–6, the map shows state-level polygons
2. Zoom in past level 7 — the map switches to county-level polygons
3. Zoom back out below 7 — switches back to state-level

**Note:** County-level choropleth coloring requires a populated `zip-to-county.json` lookup file. The current placeholder (`{}`) means counties will render with neutral fill at zoom 7+. State-level choropleth works without this file.

### 9. Map Legend

**How to test:**
1. Bottom-left corner of the map shows a floating legend
2. Legend displays the current metric name and a gradient bar
3. Min, mid, and max values are shown below the gradient
4. Switching metrics updates the legend values

### 10. Server Proxy

The Nuxt server proxies API calls to the FastAPI backend:
- `GET /api/metrics` → `http://localhost:8000/api/metrics`
- `GET /api/search` → `http://localhost:8000/api/search`
- `GET /api/listings` → `http://localhost:8000/api/listings`

**How to verify:**
```bash
# Direct backend call
curl "http://localhost:8000/api/metrics?metric=rent_to_price_ratio"

# Through Nuxt proxy
curl "http://localhost:3000/api/metrics?metric=rent_to_price_ratio"
```

Both should return the same JSON response.

## Troubleshooting

### Map shows no colored states
- Check that the backend has data: `curl http://localhost:8000/api/metrics?metric=rent_to_price_ratio`
- If the response is `[]`, the `zip_metrics` table is empty — run the crawler first
- Check browser console for GeoJSON loading errors

### Search returns no results
- Verify the `listings` table has data: `curl http://localhost:8000/api/search?q=test`
- If empty, run the crawler to populate listings

### GeoJSON files missing
- Run `frontend/scripts/fetch-geo.sh` to download them
- Check that `public/geo/us-states.json` and `public/geo/us-counties.json` exist

### Nuxt dev server fails to start
- Ensure `npm install` completed successfully in `frontend/`
- Check that port 3000 is not in use
- Verify Node.js 20+ is installed: `node --version`

### API proxy returns 500
- Ensure the FastAPI backend is running on port 8000
- Check the `NUXT_API_BASE` environment variable if using a different port:
  ```bash
  API_BASE=http://localhost:9000 npx nuxt dev
  ```

## Backend Changes

This frontend required one backend change:

**`MetricPoint` schema** (`backend/app/schemas.py`): Added `region` (state abbreviation) and `listing_count` fields. These were already on the `zip_metrics` database table but not exposed in the API. The frontend uses them for client-side aggregation from ZIP-level to state/county-level data.
