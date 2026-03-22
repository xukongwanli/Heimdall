# Known Issues & Upgrade Notes — Crawler and Database

> Supplementary material for future crawler and database improvements.
> Based on the first end-to-end crawl run on 2026-03-22.

---

## 1. Numbeo Rate Limiting (429)

**Problem:** Numbeo aggressively rate-limits after ~29 successful requests. The crawl hit 535 retries with HTTP 429 before being killed, collecting only 27 out of ~100+ US cities.

**Impact:** Incomplete city coverage. Only 18 states represented.

**Crawl stats from first run:**
- 29 successful responses / 564 total requests
- 535 retries (all 429 status)
- 56 items scraped in ~22 minutes

**Possible fixes:**
- Increase `DOWNLOAD_DELAY` to 5-10 seconds for the Numbeo spider specifically
- Add exponential backoff on 429 (currently retries at fixed intervals)
- Spread crawls across multiple sessions (e.g., crawl A-M cities, wait hours, then N-Z)
- Rotate proxies to distribute requests across IPs
- Respect any `Retry-After` header Numbeo returns

---

## 2. Geocoding Fails — All Coordinates Are NULL

**Problem:** All 54 listings have `coordinates = NULL`. The `GeocodingPipeline` uses Nominatim (free, 1 req/sec limit) but appears to fail silently for Numbeo's synthetic addresses like `"seattle city centre average"`.

**Impact:**
- The `/api/metrics` endpoint returns no data (it filters on `lat`/`lng` from `zip_metrics`)
- The frontend heatmap will be empty
- The `zip_metrics` table has 0 rows because `MetricsRefreshPipeline` computes centroids from `coordinates`

**Root cause:** Numbeo listings use synthetic addresses (e.g., `"seattle city centre average"`) which Nominatim cannot geocode. The pipeline needs a different strategy for aggregate data sources.

**Possible fixes:**
- For Numbeo specifically: geocode using just `"city, state, US"` instead of the full address
- Pre-populate a city-to-coordinates lookup table (e.g., from a US cities dataset)
- Fall back to city-level geocoding when address geocoding fails
- Use the spider itself to set lat/lng if available from the source page

---

## 3. zip_metrics Table Is Empty

**Problem:** The `zip_metrics` table has 0 rows after the crawl.

**Root cause:** Two compounding issues:
1. All `coordinates` are NULL (see issue #2), so the `AVG(ST_Y(...))` / `AVG(ST_X(...))` centroid calculation produces NULL
2. All Numbeo listings have `postal_code = ""` (empty string) — Numbeo provides city-level data, not ZIP-level

**Impact:** The `/api/metrics` endpoint returns empty results. The heatmap feature has no data.

**Possible fixes:**
- Adapt `MetricsRefreshPipeline` to group by `city + region` when `postal_code` is empty, instead of only by `postal_code`
- Or: look up representative ZIP codes for each city and populate `postal_code` in the spider
- Decouple the metrics table from `postal_code` as the sole primary key — consider a `city_metrics` table or a composite key

---

## 4. Zillow / Realtor.com / Redfin Spiders Blocked

**Problem:** All three original listing site spiders are non-functional:
- **Zillow**: Returns 403 Forbidden even with Playwright rendering
- **Realtor.com** and **Redfin**: Not tested yet but expected to block similarly

**Root cause:** These sites use aggressive anti-bot measures (CAPTCHAs, fingerprinting, IP blocking) that User-Agent rotation and Playwright alone cannot bypass.

**Impact:** No individual property listings — only Numbeo aggregate data is available.

**Possible fixes:**
- Proxy rotation service (residential proxies)
- CAPTCHA-solving service integration (e.g., 2Captcha) — middleware architecture already supports this
- Target undocumented API endpoints instead of HTML pages (some sites expose JSON APIs)
- Consider alternative data sources that are more scraper-friendly
- Use Playwright stealth plugins (`playwright-extra` with stealth plugin)

---

## 5. Numbeo Data Model Mismatch

**Problem:** Numbeo provides city-level aggregate data (avg price per sqft), not individual property listings. The current approach stores these as synthetic "listings" with workarounds:
- Buy listings: `sqft = 1`, `price = price_per_sqft` (so the pipeline computes the correct `price_per_sqft`)
- Rent listings: `sqft = 650` (assumed average 1BR size), `price = monthly_rent`

**Impact:**
- `listing_count` in metrics is misleading (2 per city regardless of actual listings)
- Mixing real listings (from future sources) with synthetic ones will skew averages
- The 650 sqft assumption for rent is a rough estimate

**Possible fixes:**
- Add a `data_type` column to distinguish `aggregate` vs `individual` listings
- Weight aggregate entries differently in metrics calculations
- Store Numbeo data directly in `zip_metrics` (or a new `city_metrics` table) bypassing the listings table entirely

---

## 6. Pylance Warning in pipelines.py

**Problem:** Pylance reports unused variable `e` at line 232 in `MetricsRefreshPipeline.close_spider()`:
```python
except Exception as e:
    session.rollback()
    raise
```

**Fix:** Change to `except Exception:` since `e` is not referenced, or log the error before re-raising.

---

## 7. Docker Image Compatibility (ARM / Apple Silicon)

**Problem:** The default `postgis/postgis:17-3.5` image has no ARM build. Required `platform: linux/amd64` to run via Rosetta emulation on Apple Silicon Macs.

**Impact:** Slower database performance due to x86 emulation overhead.

**Possible fix:** Monitor the `postgis/postgis` Docker Hub for native ARM images, or build a custom PostGIS image from the official `postgres:17` ARM image with PostGIS compiled from source.

---

## 8. Hardcoded Database Credentials

**Problem:** Database URL (`postgresql://heimdall:heimdall@localhost:5433/heimdall`) is hardcoded in four files:
- `backend/app/database.py`
- `backend/alembic.ini`
- `crawler/heimdall_crawler/settings.py`
- `crawler/heimdall_crawler/pipelines.py` (fallback defaults)

**Possible fix:** Use environment variables (`DATABASE_URL`) with a `.env` file loaded by python-dotenv. The docker-compose can set the same env var for consistency.

---

## Priority Order for Upgrades

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 1 | #2 Geocoding fix (city-level fallback) | Low | Unblocks heatmap |
| 2 | #3 zip_metrics grouping by city | Low | Unblocks /api/metrics |
| 3 | #1 Numbeo rate limiting | Medium | More city coverage |
| 4 | #8 Environment variables for DB URL | Low | Better config management |
| 5 | #5 Data model for aggregate sources | Medium | Cleaner data architecture |
| 6 | #4 Alternative listing sources | High | Individual property data |
| 7 | #7 ARM-native PostGIS image | Low | Better performance |
| 8 | #6 Pylance warning | Trivial | Code cleanliness |
