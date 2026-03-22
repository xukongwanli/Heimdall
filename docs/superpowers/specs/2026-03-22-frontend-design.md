# Heimdall Frontend Design

## Overview

Single-page Vue 3 + Nuxt 3 frontend for the Heimdall real estate intelligence platform. Displays a search bar at the top of the page and a choropleth map below. Users search by city/state/ZIP, see results in an inline table, and explore a color-filled interactive map showing real estate metrics across US administrative regions. Dark theme with minimalist, tech-inspired monospace typography.

This replaces the original two-view layout (separate `/` and `/map` routes) from the foundation spec with a single scrollable page.

## Tech Stack

- **Framework:** Vue 3 + Nuxt 3 (SSR-capable, file-based routing, auto-imports)
- **Map:** Leaflet via `@vue-leaflet/vue-leaflet`
- **Tiles:** CartoDB Dark Matter (`https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png`)
- **Boundaries:** US Census TIGER GeoJSON — simplified state + county boundaries, bundled as static assets
- **Styling:** Single `main.css` with CSS custom properties, no framework
- **Font:** JetBrains Mono (monospace, tech-inspired)

## Page Layout

Single route (`/`) with three sections, top to bottom:

1. **Nav bar** — logo ("HEIMDALL"), unit toggle ($/sqft ↔ $/m²), nav links
2. **Search section** — tagline, search input, inline results table (appears when query is active)
3. **Choropleth map** — full-width interactive Leaflet map with metric toggles, legend, zoom controls, hover/click popups

No separate routes. The map is always visible below the search section.

## Data Flow

1. **Page load** → fetch `GET /api/metrics?metric=rent_to_price_ratio` → color-fill state polygons on the map
2. **Search** → user types in search bar → debounced call to `GET /api/search?q=...` → results table appears between search bar and map
3. **Metric toggle** → user clicks Rent/Price, Buy $/sqft, or Rent $/sqft → re-fetch `GET /api/metrics?metric=...` → recolor polygons
4. **Unit toggle** → client-side conversion (1 sqft = 0.0929 m², so $/sqft × 10.764 = $/m²), no API call needed. Applies to both results table and map popups.
5. **Zoom in** → at zoom level ~7, switch from state-level to county/ZIP-level GeoJSON and re-fetch metrics with `region` filter for visible bounds
6. **Hover** → highlight polygon border, show popup with location name and metrics
7. **Click** → same as hover but popup persists until closed or another region is clicked

## Choropleth Map

### Visualization

- Each US state (zoomed out) or county/ZIP (zoomed in) is a filled polygon
- Fill color determined by the selected metric value, mapped to a continuous color scale
- State/county boundary lines visible at `#30363d` with 0.8px stroke
- 2-letter state labels centered in each state polygon
- Zoom controls (top-right)
- Color legend (bottom-left)

### Multi-Scale Rendering

| Zoom Level | Granularity | GeoJSON Source |
|-----------|-------------|---------------|
| 1–6 | US states | `us-states.json` (~200KB simplified) |
| 7+ | Counties or ZIPs | `us-counties.json` (~800KB simplified), filtered to visible bounds |

On zoom transition, old layer fades out and new layer fades in to avoid visual pop.

### Data Aggregation

The backend `/api/metrics` returns ZIP-level (`postal_code`) data. The frontend must aggregate this to state or county level for the choropleth.

**Backend change required:** Add `region` (state abbreviation, e.g. "TX") and `listing_count` fields to the `MetricPoint` response schema. These already exist on the `zip_metrics` table, just need to be exposed in the API.

**Aggregation strategy:**

- **State level (zoom 1–6):** Group `MetricPoint` entries by `region` field. Compute weighted average of `value` using `listing_count` as weight. Match to state GeoJSON polygon via the `STUSPS` (state abbreviation) property on each GeoJSON feature.
- **County level (zoom 7+):** Use a static `zip-to-county.json` lookup table (~50KB, mapping ZIP prefix to county FIPS code) bundled as a static asset. Group by county FIPS, weighted average, match to county GeoJSON via `GEOID` property.

This aggregation happens client-side in `aggregate.ts` after fetching `/api/metrics`.

### Color Scale

Continuous gradient mapped to metric value range:

| Value | Color | Hex |
|-------|-------|-----|
| Low | Blue | `#0a84ff` |
| Below avg | Green | `#32d74b` |
| Above avg | Orange | `#ff9f0a` |
| High | Red | `#ff453a` |

Scale bounds are computed from the fetched data (min/max of current metric), not hardcoded.

### Interpolation for Missing Data

Regions without listing data are rendered with a neutral dark fill (`#161b22`) and no color, clearly distinguishing them from regions with data.

**Deferred to future iteration:** IDW interpolation to estimate values for regions without data. This would require non-trivial backend work (spatial nearest-neighbor computation, new API parameters) and is not needed for v1. The choropleth is useful without it — empty regions simply appear as gaps.

### Popups

Dark card style matching site theme:
- Background: `#161b22` with `#58a6ff` border
- Shows: location name, avg buy $/sqft, avg rent $/sqft, rent-to-price ratio, listing count
- Values colored with semantic colors (green=buy, blue=rent, orange=ratio)
- Regions without data show "No data available" in the popup

## Components

### File Structure

```
frontend/
├── nuxt.config.ts          # Leaflet CSS, API proxy, dark theme meta
├── package.json
├── app.vue                 # Root layout with nav bar
├── pages/
│   └── index.vue           # Single page: search + results + map
├── components/
│   ├── NavBar.vue          # Logo, unit toggle (sqft/m²), nav links
│   ├── SearchBar.vue       # Search input with debounce, emits query
│   ├── ResultsTable.vue    # Search results table (location, buy, rent, ratio)
│   ├── ChoroplethMap.vue   # Leaflet map, GeoJSON layers, color fills, popups
│   ├── MetricToggle.vue    # Rent/Price | Buy $/sqft | Rent $/sqft buttons
│   └── MapLegend.vue       # Color scale legend overlay
├── composables/
│   ├── useMetrics.ts       # Fetch & cache /api/metrics, handle metric switching
│   ├── useSearch.ts        # Debounced /api/search calls
│   └── useUnits.ts         # sqft ↔ m² conversion state, shared across components
├── utils/
│   ├── colorScale.ts       # Maps metric values to blue→green→orange→red
│   └── aggregate.ts        # Client-side ZIP→state/county aggregation helpers
├── assets/
│   ├── geo/
│   │   ├── us-states.json  # Simplified state boundaries (~200KB)
│   │   └── us-counties.json # Simplified county boundaries (~800KB)
│   └── styles/
│       └── main.css        # Dark theme globals, monospace font imports
└── server/
    └── api/                # Nuxt server proxy routes to FastAPI
```

### Component Responsibilities

**NavBar.vue** — Static nav bar. Contains the HEIMDALL logo, unit toggle button ($/sqft ↔ $/m²), and nav links. Unit toggle state managed by `useUnits` composable, shared globally.

**SearchBar.vue** — Text input with 300ms debounce. Emits query string to parent. Shows a subtle loading indicator while API call is in-flight.

**ResultsTable.vue** — Renders search results as a table with columns: Location (constructed as `city, region` from the `SearchResult` schema; displays just `region` when `city` is null), Buy $/sqft, Rent $/sqft, Ratio. Respects current unit selection. Sortable by clicking column headers. Empty state when no search has been performed.

**ChoroplethMap.vue** — The most complex component. Manages:
- Leaflet map instance with CartoDB Dark Matter tiles
- GeoJSON layer loading (state vs county based on zoom)
- Polygon fill coloring via `colorScale` utility
- Hover highlight (border glow) and popup display
- Metric toggle integration (recolors on metric change)
- Zoom event handling for multi-scale switching

**MetricToggle.vue** — Three toggle buttons mapped to API metric values: "Rent/Price" → `rent_to_price_ratio`, "Buy $/sqft" → `avg_buy_price_per_sqft`, "Rent $/sqft" → `avg_rent_per_sqft`. Active button highlighted green. Emits selected metric string to parent.

**MapLegend.vue** — Positioned bottom-left over the map. Shows current metric name and a gradient bar with min/mid/max value labels. Updates when metric changes.

### Composables

**useMetrics.ts** — Fetches `GET /api/metrics?metric=...`. Caches results per metric to avoid redundant API calls. Exposes reactive `metrics` array, `loading` state, and `switchMetric(name)` function.

**useSearch.ts** — Wraps `GET /api/search?q=...` with 300ms debounce. Exposes reactive `results` array, `loading` state, and `search(query)` function.

**useUnits.ts** — Global reactive state for unit preference (sqft or m²). Exposes `unit` ref, `toggleUnit()` function, and `convert(value)` helper that applies the conversion factor (×10.764 for $/m²). Persists preference to localStorage.

## Visual Design

### Color Palette

| Role | Hex | Usage |
|------|-----|-------|
| Page background | `#0d1117` | Body, map background |
| Surface | `#161b22` | Nav, cards, panels, popups |
| Border subtle | `#21262d` | Dividers, inactive elements |
| Border interactive | `#30363d` | Inputs, toggles, map boundaries |
| Text primary | `#c9d1d9` | Body text, values |
| Text secondary | `#8b949e` | Labels, state abbreviations |
| Text muted | `#484f58` | Placeholders, attributions |
| Accent | `#58a6ff` | Links, active nav, popup headers |
| Active/CTA | `#238636` | Active toggle, search button |
| Buy values | `#7ee787` | Buy price per sqft in tables/popups |
| Rent values | `#79c0ff` | Rent price per sqft in tables/popups |
| Ratio values | `#ffa657` | Rent-to-price ratio in tables/popups |

### Typography

- **Primary font:** `'JetBrains Mono', 'Fira Code', ui-monospace, monospace`
- **Logo:** 18px, weight 700, letter-spacing 3px, accent color
- **Labels/tags:** 11px, letter-spacing 2px, uppercase, secondary color
- **Body:** 13px, primary color
- **Table headers:** 11px, uppercase, secondary color

### Responsive Behavior

- **Desktop (>768px):** Full layout as designed
- **Mobile (<768px):** Search bar and results stack full-width, map goes full-width with reduced height, legend repositions to bottom-center, metric toggles become a horizontal scrollable row

## Backend Changes Required

### Extend `MetricPoint` schema

Add two fields to the `MetricPoint` Pydantic model **and** update the SQLAlchemy query in `backend/app/api/metrics.py` to select `ZipMetrics.region` and `ZipMetrics.listing_count`:
- `region: str` — state abbreviation (already on `zip_metrics` table, just expose it)
- `listing_count: int` — number of listings in this ZIP (already on `zip_metrics` table)

These are needed for client-side aggregation to state/county level.

### New: Nuxt server proxy

Nuxt server routes (`frontend/server/api/`) proxy requests to FastAPI backend:
- `GET /api/metrics` → `http://localhost:8000/api/metrics`
- `GET /api/search` → `http://localhost:8000/api/search`
- `GET /api/listings` → `http://localhost:8000/api/listings`

Avoids CORS issues in production. Dev mode can also use Nuxt's `proxy` option in `nuxt.config.ts`.

## Decisions

- **Single page over two routes** — search and map are complementary, not separate workflows. Scrolling is simpler than navigation.
- **Choropleth over heatmap blobs** — real administrative boundaries give users geographic context and match the Atlas.co visual reference.
- **Leaflet over MapLibre/Deck.gl** — sufficient for current data volume, simpler setup, already in original spec. Can migrate later if needed.
- **No CSS framework** — keeps bundle small, avoids fighting framework defaults for a dark custom theme.
- **Client-side unit conversion** — sqft↔m² is a constant multiplier, no reason to involve the API.
- **GeoJSON as static assets** — state and county boundaries change rarely. Bundling avoids an extra API dependency.
- **No interpolation in v1** — regions without data shown as neutral fill. IDW interpolation deferred to future iteration to keep scope focused.
