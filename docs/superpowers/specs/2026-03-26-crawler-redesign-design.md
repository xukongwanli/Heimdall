# Three-Phase Crawler Redesign

## Overview

Redesign the Heimdall crawler from hardcoded spiders into a three-phase pipeline: discovery, probing, and extraction. The system automatically finds real estate websites via search engines, validates they're crawlable, and extracts structured listing data — all within the existing Scrapy framework.

## Architecture

### Phase 1+2: Discovery Spider (`DiscoverySpider`)

A single Scrapy spider that handles both website discovery and bot-detection probing. Runs weekly (paired with Phase 3's hourly extraction cycle).

**Discovery flow:**

1. Generate search engine queries parameterized by region: `"homes for sale in {city}"`, `"apartments for rent {city}"`, `"real estate listings {region}"`, `"property prices {country}"`
2. Fetch search result pages from Google/Bing
3. Skip URLs whose domain already exists in `discovered_sites` table
4. Fetch each candidate page
5. Send page text to DeepSeek V3.2 for classification — the LLM returns: `{"has_real_estate_data": true, "data_types": ["price", "sqft", "address"], "confidence": 0.9}`
6. If classified as having real estate data, proceed to probing

**Probing flow (escalating speed test):**

1. Level 1: 1 request / 10 seconds (fetch 3 pages)
2. Level 2: 1 request / 5 seconds (fetch 3 pages)
3. Level 3: 1 request / 2 seconds (fetch 3 pages)
4. Level 4: 1 request / 1 second (fetch 3 pages)

**Abandonment rules:**
- CAPTCHA or antibot detection (Cloudflare challenge, Akamai Bot Manager, PerimeterX, DataDome, JavaScript verification redirects, keywords like "captcha", "verify you are human", "challenge") at any level -> abandon immediately
- HTTP 429 (rate limiting) -> record the previous level's rate as `max_crawl_rate`, site is approved
- All levels pass -> record maximum rate, site is approved

**Result:** Insert approved sites into `discovered_sites` table with `status='approved'`.

### Phase 3: Extraction Spider (`ExtractionSpider`)

Runs on the ~1-hour cycle against all approved sites from `discovered_sites`.

**Extraction flow:**

1. Load all approved sites from `discovered_sites` table
2. For each site, set per-domain `DOWNLOAD_DELAY` based on its `max_crawl_rate`
3. Start at `root_url`, follow links matching listing patterns (`/listing/`, `/property/`, `/for-sale/`, `/rent/`, pagination)
4. Cap depth at 3 levels from root, cap 200 pages per site per run
5. For each page, determine extraction method:

**Extraction method priority:**

1. Check `extraction_selectors` table for cached method -> use cached selectors
2. Try structured data detection (cheap, no LLM cost):
   - JSON-LD (`RealEstateListing`, `Product`)
   - Open Graph tags
   - `__NEXT_DATA__` embedded JSON
   - Common CSS patterns
3. If no structured data found -> send page to DeepSeek to generate CSS selectors for: price, address, sqft, bedrooms, listing_type
4. Cache the working method in `extraction_selectors` table

**Selector validation:** If cached selectors return empty results for >50% of pages, mark stale, re-trigger DeepSeek once. If new selectors also fail, mark site as `retired`.

**Output:** Yields `ListingItem` objects into the existing pipeline chain (CleaningPipeline -> EnrichmentPipeline -> GeocodingPipeline -> PostgresPipeline -> MetricsRefreshPipeline). No pipeline changes needed.

### Deduplication

Address-based. Normalize addresses (existing `CleaningPipeline` logic), then the existing `PostgresPipeline` UPSERT handles it — conflict key is `(source, address, listing_type)` where `source` is the discovered site's domain.

### Numbeo Spider

Kept as-is. It's the only currently working spider and provides reliable aggregate city-level data. Runs alongside `ExtractionSpider` during extraction cycles.

## Database Schema Changes

### `discovered_sites` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | Primary key |
| `root_url` | TEXT UNIQUE | Root domain URL |
| `domain` | TEXT | Extracted domain for grouping |
| `discovery_query` | TEXT | The search query that found this site |
| `llm_classification` | JSONB | DeepSeek's assessment (data types, confidence) |
| `max_crawl_rate` | FLOAT | Sustainable requests/second from probing |
| `extraction_method` | TEXT | `structured` or `llm` |
| `status` | TEXT | `approved`, `blocked`, `retired` |
| `last_probed_at` | TIMESTAMP | When Phase 2 last tested this site |
| `last_extracted_at` | TIMESTAMP | When Phase 3 last crawled this site |
| `created_at` | TIMESTAMP | First discovery time |

### `extraction_selectors` table

| Column | Type | Purpose |
|--------|------|---------|
| `id` | UUID PK | Primary key |
| `site_id` | UUID FK | References `discovered_sites` |
| `page_pattern` | TEXT | URL pattern this selector applies to |
| `selectors` | JSONB | CSS/XPath selectors for each field |
| `structured_data_type` | TEXT | `json-ld`, `open-graph`, `next-data`, etc. |
| `created_at` | TIMESTAMP | When selectors were generated |
| `validated_at` | TIMESTAMP | Last time selectors confirmed working |

## DeepSeek Integration

A utility module `heimdall_crawler/llm.py` wraps the DeepSeek API.

Configuration in `settings.py`:
```python
LLM_API_KEY = ""  # User fills this in
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-v3.2"
```

Two LLM functions:
1. **classify_page(text) -> dict** — Phase 1 classification. Returns `{has_real_estate_data, data_types, confidence}`
2. **generate_selectors(html) -> dict** — Phase 3 fallback. Returns CSS selectors for listing fields

Timeout: 30 seconds per call. No retries — skip on failure.

## Antibot Detection

A utility module `heimdall_crawler/antibot.py` with a single function:

**`detect_antibot(response) -> bool`** — Returns `True` if the response contains antibot signals:
- CAPTCHA keywords in page content (`captcha`, `verify you are human`, `challenge`)
- Known antibot service signatures (Cloudflare challenge, Akamai Bot Manager, PerimeterX, DataDome)
- JavaScript-only redirects to verification pages

Used in both DiscoverySpider (Phase 2 probing) and ExtractionSpider (to mark sites as `blocked` if they start showing antibot mid-extraction).

## Orchestration

Updated `run_all.py` with mode-based invocation:

```
python run_all.py discover [--regions TX CA FL]    # Phase 1+2: weekly discovery
python run_all.py extract  [--regions TX CA FL]    # Phase 3: hourly extraction
python run_all.py all      [--regions TX CA FL]    # Both in sequence
```

**`discover` mode:** Runs `DiscoverySpider` with region-based search queries.

**`extract` mode:** Runs `NumbeoSpider`, then `ExtractionSpider` against all approved sites.

**`all` mode:** Runs discover then extract in sequence.

Scheduling is external (cron, etc.) — `run_all.py` handles single invocations.

## File Changes

### Files to add
- `heimdall_crawler/spiders/discovery.py` — DiscoverySpider (Phase 1+2)
- `heimdall_crawler/spiders/extraction.py` — ExtractionSpider (Phase 3)
- `heimdall_crawler/llm.py` — DeepSeek API wrapper
- `heimdall_crawler/antibot.py` — Antibot detection utilities

### Files to modify
- `heimdall_crawler/settings.py` — Add LLM config keys
- `run_all.py` — Rewrite with discover/extract/all modes

### Files to remove
- `heimdall_crawler/spiders/realtor.py` — blocked, replaced by generic extraction
- `heimdall_crawler/spiders/redfin.py` — blocked, replaced by generic extraction
- `heimdall_crawler/spiders/zillow.py` — blocked, not in run_all.py

### Files unchanged
- `heimdall_crawler/items.py` — ListingItem fields cover all needs
- `heimdall_crawler/pipelines.py` — Existing 5-stage chain works as-is
- `heimdall_crawler/middlewares.py` — Existing middleware applies to new spiders
- `heimdall_crawler/spiders/numbeo.py` — Kept as reliable data source

## Error Handling

### DeepSeek API failures
- Unreachable or error -> skip that URL, log it. Don't block the run.
- 30-second timeout per call. Exceeded -> treat as skip.
- No retries on LLM calls.

### Site behavior changes during extraction
- Antibot responses during Phase 3 -> mark site `status='blocked'`. Won't be crawled until next discovery cycle re-probes.
- Unreachable (5xx, timeouts) for 3 consecutive extraction runs -> mark as `retired`.

### Selector staleness
- >50% empty results -> regenerate selectors via DeepSeek once. If new selectors also fail -> mark site `retired`.

### Search engine rate limiting
- Uses existing `BackoffRetryMiddleware` and `DOWNLOAD_DELAY`. If search engines block, discovery degrades gracefully — Phase 3 continues on already-approved sites.

### Storage budget
- 200 GB cap per project spec. 200-page cap per site per run + address dedup bounds growth. `last_extracted_at` enables future data aging if needed.
