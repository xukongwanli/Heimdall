# Not Sure Problems

Items where it's unclear whether they are still issues or have been resolved.

---

## 1. Numbeo Spider Coverage After Rate Limiting Fix

The Numbeo spider collected only 27/100+ US cities due to 429 rate limiting. It's unclear whether subsequent crawl runs have improved coverage, or if the 18-state limitation still holds. No code fix was made — this depends on runtime behavior and retry timing.

**How to verify:** Run `scrapy crawl numbeo` and check how many cities/states are collected. Or query the DB: `SELECT COUNT(DISTINCT city), COUNT(DISTINCT region) FROM listings WHERE source = 'numbeo'`.

---

## 2. Zillow/Realtor/Redfin Spider Status

These spiders exist in the codebase but were reported as blocked (403). It's unclear whether they have been updated or tested since the initial report. The spider files still exist at `crawler/heimdall_crawler/spiders/` but may be non-functional.

**How to verify:** Try running each spider individually (`scrapy crawl zillow`, etc.) and check for 403/CAPTCHA errors.

---

## 3. Docker ARM Image Availability

The `postgis/postgis:17-3.5` image required `platform: linux/amd64` for Apple Silicon. PostGIS may have released native ARM images since the issue was first documented (2026-03-22). The `docker-compose.yml` still has `platform: linux/amd64`.

**How to verify:** Check Docker Hub for `postgis/postgis` ARM builds, or try removing `platform: linux/amd64` from `docker-compose.yml` and see if the container starts natively.

---

## 4. Frontend `zip-to-county.json` Placeholder

The frontend design spec and frontend-guide.md mention a `zip-to-county.json` lookup file for county-level choropleth rendering. The pipeline enrichment work removed the need for client-side ZIP-to-county aggregation (backend now serves pre-aggregated data by level). However, it's unclear if the placeholder file `frontend/public/geo/zip-to-county.json` still exists and whether anything references it.

**How to verify:** Check if the file exists and grep the frontend source for `zip-to-county`.
