# Known Issues & Upgrade Notes

> Supplementary material for future improvements.
> Last updated: 2026-03-25.

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

## 2. Zillow / Realtor.com / Redfin Spiders Blocked

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

## 3. Numbeo Data Model Mismatch

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
- Store Numbeo data directly in `region_metrics` bypassing the listings table entirely

---

## 4. Docker Image Compatibility (ARM / Apple Silicon)

**Problem:** The default `postgis/postgis:17-3.5` image has no ARM build. Required `platform: linux/amd64` to run via Rosetta emulation on Apple Silicon Macs.

**Impact:** Slower database performance due to x86 emulation overhead.

**Possible fix:** Monitor the `postgis/postgis` Docker Hub for native ARM images, or build a custom PostGIS image from the official `postgres:17` ARM image with PostGIS compiled from source.

---

## 5. Hardcoded Database Credentials

**Problem:** Database URL (`postgresql://heimdall:heimdall@localhost:5433/heimdall`) is hardcoded in multiple files:
- `backend/app/database.py`
- `backend/alembic.ini`
- `crawler/heimdall_crawler/settings.py`
- `crawler/heimdall_crawler/pipelines.py` (fallback defaults)
- `scripts/populate_geo_reference.py`
- Test files (`tests/test_enrichment.py`, `tests/test_region_metrics.py`)

**Possible fix:** Use environment variables (`DATABASE_URL`) with a `.env` file loaded by python-dotenv. The docker-compose can set the same env var for consistency.

---

## 6. Outdated Documentation

**Problem:** Several docs reference the old `zip_metrics` table, client-side ZIP-to-county aggregation, and the pre-enrichment pipeline architecture. These docs were written before the pipeline enrichment work (2026-03-24) and have not been updated:
- `docs/superpowers/specs/2026-03-21-heimdall-foundation-design.md` — references `zip_metrics` table, old pipeline chain (no EnrichmentPipeline), old `/api/metrics` response shape
- `docs/superpowers/specs/2026-03-22-frontend-design.md` — references client-side ZIP→county aggregation via `zip-to-county.json`, old `MetricPoint` schema with `postal_code`
- `docs/frontend-guide.md` — references `zip_metrics`, `zip-to-county.json` placeholder, old troubleshooting that says "zip_metrics table is empty"

**Impact:** Misleading for anyone reading the specs. The actual implementation uses `region_metrics`, server-side multi-level aggregation, and `EnrichmentPipeline`.

**Fix:** Update these docs to reflect the current architecture, or add a notice that they are historical and superseded by the pipeline enrichment spec.

---

## 7. Test DB URL Mismatch

**Problem:** 5 pre-existing tests in `tests/test_pipelines.py` use `postgresql://localhost/heimdall` (port 5432, no password) while the actual database runs on port 5433 with user/password `heimdall`. These tests fail with connection errors.

**Impact:** Test suite reports false failures. Only tests using the correct URL (`postgresql://heimdall:heimdall@localhost:5433/heimdall`) pass.

**Fix:** Standardize all test DB URLs to match the docker-compose configuration, or use a shared `DATABASE_URL` env var (see issue #5).

---

## Priority Order for Upgrades

| Priority | Issue | Effort | Impact |
|----------|-------|--------|--------|
| 1 | #5 Environment variables for DB URL | Low | Fixes hardcoded creds + test URL mismatch |
| 2 | #7 Test DB URL mismatch | Low | Reliable test suite |
| 3 | #1 Numbeo rate limiting | Medium | More city coverage |
| 4 | #3 Data model for aggregate sources | Medium | Cleaner data architecture |
| 5 | #2 Alternative listing sources | High | Individual property data |
| 6 | #6 Outdated documentation | Low | Accurate docs |
| 7 | #4 ARM-native PostGIS image | Low | Better performance |

---

## Resolved Issues (removed from this doc)

For historical reference, these issues were resolved by the pipeline enrichment work (PR #1, merged 2026-03-25):

- **Geocoding Fails — All Coordinates NULL** — `EnrichmentPipeline` fills lat/lng from `geo_reference` table before `GeocodingPipeline` runs. GeocodingPipeline now skips when coordinates are already present.
- **zip_metrics Table Is Empty** — Replaced by `region_metrics` with multi-level aggregation (state, county, city, ZIP). `MetricsRefreshPipeline` now aggregates at all four levels.
- **Pylance Warning (unused variable `e`)** — The `MetricsRefreshPipeline` was rewritten; the current `except Exception as e` at line 395 properly uses `e` in the error log.
