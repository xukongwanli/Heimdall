# Three-Phase Crawler Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign the crawler into a three-phase pipeline (discover, probe, extract) that automatically finds, validates, and scrapes real estate websites using DeepSeek LLM classification.

**Architecture:** Two new Scrapy spiders — `DiscoverySpider` (Phase 1+2) and `ExtractionSpider` (Phase 3) — join the existing `NumbeoSpider`. Discovery uses search engines + DeepSeek to find real estate sites, probes them for antibot measures, and records approved sites in PostgreSQL. Extraction reads approved sites from DB and uses cached selectors (structured data or LLM-generated) to extract listings into the existing pipeline chain.

**Tech Stack:** Scrapy 2.12, PostgreSQL + PostGIS, DeepSeek V3.2 API, Alembic migrations, pytest

**Spec:** `docs/superpowers/specs/2026-03-26-crawler-redesign-design.md`

---

## File Structure

### New files

| File | Responsibility |
|------|---------------|
| `crawler/heimdall_crawler/llm.py` | DeepSeek API wrapper — classify pages, generate selectors |
| `crawler/heimdall_crawler/antibot.py` | Detect CAPTCHA/antibot signals in HTTP responses |
| `crawler/heimdall_crawler/spiders/discovery.py` | DiscoverySpider — Phase 1+2 (search, classify, probe) |
| `crawler/heimdall_crawler/spiders/extraction.py` | ExtractionSpider — Phase 3 (extract from approved sites) |
| `backend/alembic/versions/xxx_add_discovered_sites.py` | Alembic migration for new tables |
| `backend/app/models.py` | Add `DiscoveredSite` and `ExtractionSelector` ORM models |
| `tests/test_llm.py` | Tests for LLM wrapper |
| `tests/test_antibot.py` | Tests for antibot detection |
| `tests/test_discovery.py` | Tests for DiscoverySpider logic |
| `tests/test_extraction.py` | Tests for ExtractionSpider logic |

### Modified files

| File | Changes |
|------|---------|
| `crawler/heimdall_crawler/settings.py` | Add LLM config keys |
| `crawler/run_all.py` | Rewrite with discover/extract/all modes |
| `crawler/requirements.txt` | Add `httpx` for async DeepSeek calls |

### Removed files

| File | Reason |
|------|--------|
| `crawler/heimdall_crawler/spiders/realtor.py` | Blocked, replaced by generic extraction |
| `crawler/heimdall_crawler/spiders/redfin.py` | Blocked, replaced by generic extraction |
| `crawler/heimdall_crawler/spiders/zillow.py` | Blocked, never worked |

---

## Task 1: Database Schema — Migration and ORM Models

**Files:**
- Modify: `backend/app/models.py`
- Create: `backend/alembic/versions/` (auto-generated migration)
- Test: `tests/test_models.py`

- [ ] **Step 1: Write failing test for DiscoveredSite model**

Create `tests/test_models.py` (append to existing):

```python
# Append to tests/test_models.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from backend.app.models import DiscoveredSite, ExtractionSelector


def test_discovered_site_has_required_columns():
    cols = {c.name for c in DiscoveredSite.__table__.columns}
    expected = {
        'id', 'root_url', 'domain', 'discovery_query',
        'llm_classification', 'max_crawl_rate', 'extraction_method',
        'status', 'last_probed_at', 'last_extracted_at', 'created_at',
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"


def test_extraction_selector_has_required_columns():
    cols = {c.name for c in ExtractionSelector.__table__.columns}
    expected = {
        'id', 'site_id', 'page_pattern', 'selectors',
        'structured_data_type', 'created_at', 'validated_at',
    }
    assert expected.issubset(cols), f"Missing columns: {expected - cols}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_models.py::test_discovered_site_has_required_columns tests/test_models.py::test_extraction_selector_has_required_columns -v`

Expected: FAIL with `ImportError: cannot import name 'DiscoveredSite'`

- [ ] **Step 3: Add ORM models to backend/app/models.py**

Add these classes after the existing `RegionMetrics` class:

```python
class DiscoveredSite(Base):
    __tablename__ = "discovered_sites"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    root_url = Column(Text, nullable=False, unique=True)
    domain = Column(Text, nullable=False)
    discovery_query = Column(Text, nullable=True)
    llm_classification = Column(sa.JSON, nullable=True)
    max_crawl_rate = Column(Numeric, nullable=True)
    extraction_method = Column(String(20), nullable=True)  # 'structured' or 'llm'
    status = Column(String(20), nullable=False, server_default="approved")
    last_probed_at = Column(DateTime(timezone=True), nullable=True)
    last_extracted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)

    __table_args__ = (
        Index("ix_discovered_sites_domain", "domain"),
        Index("ix_discovered_sites_status", "status"),
    )


class ExtractionSelector(Base):
    __tablename__ = "extraction_selectors"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    site_id = Column(UUID(as_uuid=True), sa.ForeignKey("discovered_sites.id"), nullable=False)
    page_pattern = Column(Text, nullable=False)
    selectors = Column(sa.JSON, nullable=True)
    structured_data_type = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    validated_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_extraction_selectors_site_id", "site_id"),
    )
```

Note: The existing models.py imports `from sqlalchemy import ...` — add `JSON, ForeignKey` to that import. Also `import sqlalchemy as sa` is not used — use the direct imports instead, matching existing style. Use `JSON` from `sqlalchemy.dialects.postgresql` for JSONB support, or use `sa.JSON` for basic JSON. Match the existing pattern of direct Column imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_models.py::test_discovered_site_has_required_columns tests/test_models.py::test_extraction_selector_has_required_columns -v`

Expected: PASS

- [ ] **Step 5: Generate Alembic migration**

Run: `cd /Users/yourstruly/Documents/heimdall/backend && alembic revision --autogenerate -m "add discovered_sites and extraction_selectors tables"`

Verify the generated migration contains:
- `create_table('discovered_sites', ...)` with all columns
- `create_table('extraction_selectors', ...)` with all columns and foreign key
- Appropriate indexes

- [ ] **Step 6: Apply migration**

Run: `cd /Users/yourstruly/Documents/heimdall/backend && alembic upgrade head`

Expected: Tables created successfully.

- [ ] **Step 7: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/ tests/test_models.py
git commit -m "feat: add discovered_sites and extraction_selectors schema"
```

---

## Task 2: LLM Wrapper Module

**Files:**
- Create: `crawler/heimdall_crawler/llm.py`
- Modify: `crawler/heimdall_crawler/settings.py`
- Modify: `crawler/requirements.txt`
- Test: `tests/test_llm.py`

- [ ] **Step 1: Add httpx dependency**

Add `httpx==0.28.1` to `crawler/requirements.txt` and install:

Run: `cd /Users/yourstruly/Documents/heimdall/crawler && pip install httpx==0.28.1`

- [ ] **Step 2: Add LLM settings to settings.py**

Append to `crawler/heimdall_crawler/settings.py`:

```python
# LLM — DeepSeek for page classification and selector generation
LLM_API_KEY = ""  # Set your DeepSeek API key here
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-v3.2"
LLM_TIMEOUT = 30  # seconds
```

- [ ] **Step 3: Write failing test for classify_page**

Create `tests/test_llm.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from unittest.mock import patch, MagicMock
import json
from heimdall_crawler.llm import classify_page, generate_selectors


def test_classify_page_returns_classification():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "has_real_estate_data": True,
                    "data_types": ["price", "address", "sqft"],
                    "confidence": 0.92,
                })
            }
        }]
    }

    with patch("heimdall_crawler.llm.httpx.post", return_value=mock_response):
        result = classify_page("Sample page with homes for sale, $450,000, 1800 sqft", api_key="test-key")

    assert result["has_real_estate_data"] is True
    assert "price" in result["data_types"]
    assert result["confidence"] > 0.5


def test_classify_page_returns_none_on_timeout():
    with patch("heimdall_crawler.llm.httpx.post", side_effect=Exception("timeout")):
        result = classify_page("some text", api_key="test-key")

    assert result is None


def test_classify_page_returns_none_on_bad_json():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{"message": {"content": "not valid json"}}]
    }

    with patch("heimdall_crawler.llm.httpx.post", return_value=mock_response):
        result = classify_page("some text", api_key="test-key")

    assert result is None
```

- [ ] **Step 4: Run test to verify it fails**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_llm.py::test_classify_page_returns_classification tests/test_llm.py::test_classify_page_returns_none_on_timeout tests/test_llm.py::test_classify_page_returns_none_on_bad_json -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'heimdall_crawler.llm'`

- [ ] **Step 5: Implement llm.py**

Create `crawler/heimdall_crawler/llm.py`:

```python
import json
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v3.2"
DEFAULT_TIMEOUT = 30


def _call_llm(messages, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """Make a chat completion request to the DeepSeek API. Returns the content string or None."""
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def classify_page(page_text, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """Ask DeepSeek whether a page contains real estate listing data.

    Returns a dict like:
        {"has_real_estate_data": True, "data_types": ["price", "sqft"], "confidence": 0.9}
    or None on failure.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze web pages to determine if they contain real estate listing data. "
                "Respond ONLY with a JSON object: "
                '{"has_real_estate_data": bool, "data_types": [list of: "price", "address", "sqft", "bedrooms", "rent", "listing_type"], "confidence": float 0-1}'
            ),
        },
        {
            "role": "user",
            "content": f"Does this page contain real estate listing data?\n\n{page_text[:4000]}",
        },
    ]

    content = _call_llm(messages, api_key, base_url, model, timeout)
    if content is None:
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON: %s", content[:200])
        return None


def generate_selectors(page_html, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """Ask DeepSeek to generate CSS selectors for extracting listing fields from a page.

    Returns a dict like:
        {"price": "span.price", "address": "h2.address", "sqft": "span.sqft", ...}
    or None on failure.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze HTML to generate CSS selectors for extracting real estate listing data. "
                "Respond ONLY with a JSON object mapping field names to CSS selectors. "
                "Fields: price, address, sqft, bedrooms, listing_type, city, region, postal_code. "
                "Only include fields you can find selectors for. "
                'Example: {"price": "span.listing-price", "address": "h2.property-address"}'
            ),
        },
        {
            "role": "user",
            "content": f"Generate CSS selectors for real estate data in this HTML:\n\n{page_html[:6000]}",
        },
    ]

    content = _call_llm(messages, api_key, base_url, model, timeout)
    if content is None:
        return None

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON selectors: %s", content[:200])
        return None
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_llm.py -v`

Expected: All 3 tests PASS

- [ ] **Step 7: Write failing test for generate_selectors**

Append to `tests/test_llm.py`:

```python
def test_generate_selectors_returns_selectors():
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "choices": [{
            "message": {
                "content": json.dumps({
                    "price": "span.listing-price",
                    "address": "h2.property-address",
                    "sqft": "span.sqft-value",
                })
            }
        }]
    }

    with patch("heimdall_crawler.llm.httpx.post", return_value=mock_response):
        result = generate_selectors("<html><span class='listing-price'>$450k</span></html>", api_key="test-key")

    assert result["price"] == "span.listing-price"
    assert result["address"] == "h2.property-address"


def test_generate_selectors_returns_none_on_failure():
    with patch("heimdall_crawler.llm.httpx.post", side_effect=Exception("error")):
        result = generate_selectors("<html></html>", api_key="test-key")

    assert result is None
```

- [ ] **Step 8: Run all LLM tests to verify they pass**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_llm.py -v`

Expected: All 5 tests PASS

- [ ] **Step 9: Commit**

```bash
git add crawler/heimdall_crawler/llm.py crawler/heimdall_crawler/settings.py crawler/requirements.txt tests/test_llm.py
git commit -m "feat: add DeepSeek LLM wrapper for page classification and selector generation"
```

---

## Task 3: Antibot Detection Module

**Files:**
- Create: `crawler/heimdall_crawler/antibot.py`
- Test: `tests/test_antibot.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_antibot.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from unittest.mock import MagicMock
from heimdall_crawler.antibot import detect_antibot


def _make_response(body_text, url="https://example.com"):
    resp = MagicMock()
    resp.text = body_text
    resp.url = url
    resp.status = 200
    return resp


def test_detects_captcha_keyword():
    resp = _make_response("Please complete the CAPTCHA to continue")
    assert detect_antibot(resp) is True


def test_detects_cloudflare_challenge():
    resp = _make_response('<div class="cf-browser-verification">Checking your browser</div>')
    assert detect_antibot(resp) is True


def test_detects_verify_human():
    resp = _make_response("We need to verify you are human before proceeding")
    assert detect_antibot(resp) is True


def test_detects_perimeterx():
    resp = _make_response("blocked by PerimeterX")
    assert detect_antibot(resp) is True


def test_detects_datadome():
    resp = _make_response('<script src="https://js.datadome.co/tags.js"></script>')
    assert detect_antibot(resp) is True


def test_normal_page_passes():
    resp = _make_response("<html><body><h1>Homes for sale</h1><p>$450,000</p></body></html>")
    assert detect_antibot(resp) is False


def test_empty_page_passes():
    resp = _make_response("")
    assert detect_antibot(resp) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_antibot.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'heimdall_crawler.antibot'`

- [ ] **Step 3: Implement antibot.py**

Create `crawler/heimdall_crawler/antibot.py`:

```python
import re
import logging

logger = logging.getLogger(__name__)

# Case-insensitive patterns that indicate antibot measures
ANTIBOT_PATTERNS = [
    # CAPTCHA
    r'captcha',
    r'recaptcha',
    r'hcaptcha',
    # Human verification
    r'verify\s+(you\s+are|that\s+you\s+are)\s+human',
    r'are\s+you\s+a\s+robot',
    r'bot\s+detection',
    r'please\s+complete\s+the\s+challenge',
    # Cloudflare
    r'cf-browser-verification',
    r'checking\s+your\s+browser',
    r'cloudflare\s+ray\s+id',
    # Akamai Bot Manager
    r'akamai\s+bot\s+manager',
    r'akam/\d+',
    # PerimeterX
    r'perimeterx',
    r'_px\d*\.js',
    r'blocked\s+by\s+px',
    # DataDome
    r'datadome',
    r'js\.datadome\.co',
    # Generic
    r'access\s+denied.*automated',
    r'suspected\s+bot',
]

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in ANTIBOT_PATTERNS]


def detect_antibot(response):
    """Check if a Scrapy response contains antibot signals.

    Args:
        response: A Scrapy Response object (or mock with .text attribute).

    Returns:
        True if antibot measures are detected, False otherwise.
    """
    text = response.text
    if not text:
        return False

    for pattern in _compiled_patterns:
        if pattern.search(text):
            logger.info("Antibot detected on %s: matched pattern %s", response.url, pattern.pattern)
            return True

    return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_antibot.py -v`

Expected: All 7 tests PASS

- [ ] **Step 5: Commit**

```bash
git add crawler/heimdall_crawler/antibot.py tests/test_antibot.py
git commit -m "feat: add antibot detection module for CAPTCHA and bot-blocker identification"
```

---

## Task 4: Discovery Spider (Phase 1+2)

**Files:**
- Create: `crawler/heimdall_crawler/spiders/discovery.py`
- Test: `tests/test_discovery.py`

- [ ] **Step 1: Write failing tests for search query generation**

Create `tests/test_discovery.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.spiders.discovery import DiscoverySpider


def test_generates_search_queries():
    spider = DiscoverySpider(regions="TX,CA")
    queries = spider._build_search_queries()
    assert len(queries) > 0
    assert any("TX" in q for q in queries)
    assert any("CA" in q for q in queries)


def test_generates_queries_for_single_region():
    spider = DiscoverySpider(regions="TX")
    queries = spider._build_search_queries()
    assert all("TX" in q or "Texas" in q for q in queries)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_discovery.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement DiscoverySpider skeleton with query generation**

Create `crawler/heimdall_crawler/spiders/discovery.py`:

```python
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy
from scrapy.exceptions import CloseSpider
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from heimdall_crawler.antibot import detect_antibot
from heimdall_crawler.llm import classify_page as llm_classify_page

logger = logging.getLogger(__name__)

# US state abbreviation to full name mapping (for search queries)
STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
    "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
    "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
    "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
    "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
    "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico", "NY": "New York",
    "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio", "OK": "Oklahoma",
    "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island", "SC": "South Carolina",
    "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
    "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West Virginia",
    "WI": "Wisconsin", "WY": "Wyoming",
}

SEARCH_TEMPLATES = [
    "homes for sale in {state_name}",
    "apartments for rent {state_name}",
    "real estate listings {state_name}",
    "property prices {state_name}",
]

# Probe levels: (delay_seconds, num_requests)
PROBE_LEVELS = [
    (10, 3),
    (5, 3),
    (2, 3),
    (1, 3),
]


class DiscoverySpider(scrapy.Spider):
    """Phase 1+2: Discover real estate websites and probe for crawlability.

    Usage:
        scrapy crawl discovery -a regions=TX,CA,FL
    """

    name = "discovery"

    def __init__(self, regions="TX", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region_list = [r.strip().upper() for r in regions.split(",")]
        self._known_domains = set()
        self._db_session = None
        self._api_key = None

    def _build_search_queries(self):
        """Generate search queries for all regions."""
        queries = []
        for region in self.region_list:
            state_name = STATE_NAMES.get(region, region)
            for template in SEARCH_TEMPLATES:
                queries.append(template.format(state_name=state_name))
        return queries

    def open_spider(self, spider):
        pass  # DB connection setup handled in start_requests

    def start_requests(self):
        db_url = self.settings.get("DATABASE_URL", "postgresql://heimdall:heimdall@localhost:5433/heimdall")
        self._api_key = self.settings.get("LLM_API_KEY", "")
        if not self._api_key:
            raise CloseSpider("LLM_API_KEY not set in settings.py")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        self._db_session_factory = Session
        self._engine = engine

        # Load known domains to skip
        session = Session()
        try:
            rows = session.execute(text("SELECT domain FROM discovered_sites")).fetchall()
            self._known_domains = {row[0] for row in rows}
            logger.info("Loaded %d known domains", len(self._known_domains))
        finally:
            session.close()

        # Generate search queries and submit to Google
        queries = self._build_search_queries()
        for query in queries:
            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            yield scrapy.Request(
                search_url,
                callback=self.parse_search_results,
                meta={"query": query},
            )

    def parse_search_results(self, response):
        """Phase 1: Extract candidate URLs from search results."""
        query = response.meta["query"]

        # Google organic result links
        for link in response.css("a::attr(href)").getall():
            if not link.startswith("http"):
                continue

            domain = urlparse(link).netloc
            # Skip known domains, google itself, and common non-listing sites
            if domain in self._known_domains:
                continue
            if any(skip in domain for skip in ["google.", "youtube.", "wikipedia.", "facebook.", "twitter."]):
                continue

            self._known_domains.add(domain)  # Don't visit same domain twice in one run
            yield scrapy.Request(
                link,
                callback=self.check_candidate,
                meta={"query": query, "domain": domain},
                errback=self.handle_error,
            )

    def check_candidate(self, response):
        """Phase 1: Send page to DeepSeek for classification."""
        if detect_antibot(response):
            logger.info("Antibot on initial visit to %s — skipping", response.url)
            return

        page_text = response.css("body *::text").getall()
        page_text = " ".join(t.strip() for t in page_text if t.strip())[:4000]

        if not page_text:
            return

        result = llm_classify_page(
            page_text,
            api_key=self._api_key,
            base_url=self.settings.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
            model=self.settings.get("LLM_MODEL", "deepseek-v3.2"),
            timeout=self.settings.getint("LLM_TIMEOUT", 30),
        )

        if result is None:
            logger.info("LLM classification failed for %s — skipping", response.url)
            return

        if not result.get("has_real_estate_data"):
            logger.info("No real estate data on %s (confidence: %s)", response.url, result.get("confidence"))
            return

        logger.info("Real estate data found on %s: %s", response.url, result.get("data_types"))

        # Proceed to Phase 2: probing
        yield scrapy.Request(
            response.url,
            callback=self.probe_site,
            dont_filter=True,
            meta={
                "query": response.meta["query"],
                "domain": response.meta["domain"],
                "root_url": response.url,
                "llm_classification": result,
                "probe_level": 0,
                "probe_count": 0,
                "probe_links": [],
            },
        )

    def probe_site(self, response):
        """Phase 2: Escalating speed probe to test crawlability."""
        meta = response.meta
        probe_level = meta["probe_level"]
        probe_count = meta["probe_count"]

        # Check for antibot on probe response
        if detect_antibot(response):
            logger.info("Antibot detected on %s at probe level %d — abandoning", meta["root_url"], probe_level)
            return

        probe_count += 1
        delay, requests_needed = PROBE_LEVELS[probe_level]

        if probe_count >= requests_needed:
            # Level passed, advance to next level
            next_level = probe_level + 1
            if next_level >= len(PROBE_LEVELS):
                # All levels passed — record max rate
                max_rate = 1.0 / PROBE_LEVELS[-1][0]
                self._save_approved_site(meta, max_rate)
                return

            # Collect links for next probe level
            links = self._collect_probe_links(response)
            if not links:
                # No more links to probe — record current level's rate
                max_rate = 1.0 / delay
                self._save_approved_site(meta, max_rate)
                return

            for link in links[:PROBE_LEVELS[next_level][1]]:
                next_delay = PROBE_LEVELS[next_level][0]
                yield scrapy.Request(
                    response.urljoin(link),
                    callback=self.probe_site,
                    dont_filter=True,
                    meta={
                        **meta,
                        "probe_level": next_level,
                        "probe_count": 0,
                        "download_delay": next_delay,
                    },
                )
            return

        # Continue at current level — fetch more pages
        links = self._collect_probe_links(response)
        if links:
            yield scrapy.Request(
                response.urljoin(links[0]),
                callback=self.probe_site,
                dont_filter=True,
                meta={
                    **meta,
                    "probe_count": probe_count,
                    "download_delay": delay,
                },
            )
        else:
            # No more links — approve at current rate
            max_rate = 1.0 / delay
            self._save_approved_site(meta, max_rate)

    def _collect_probe_links(self, response):
        """Gather internal links from the page for probing."""
        domain = urlparse(response.url).netloc
        links = []
        for href in response.css("a::attr(href)").getall():
            full_url = response.urljoin(href)
            if urlparse(full_url).netloc == domain:
                links.append(href)
        return links[:20]  # Cap to avoid excessive link collection

    def _save_approved_site(self, meta, max_crawl_rate):
        """Insert an approved site into discovered_sites."""
        session = self._db_session_factory()
        try:
            now = datetime.now(timezone.utc)
            session.execute(
                text("""
                    INSERT INTO discovered_sites (id, root_url, domain, discovery_query,
                        llm_classification, max_crawl_rate, status, last_probed_at, created_at)
                    VALUES (gen_random_uuid(), :root_url, :domain, :query,
                        :classification, :max_rate, 'approved', :now, :now)
                    ON CONFLICT (root_url) DO UPDATE SET
                        max_crawl_rate = :max_rate,
                        last_probed_at = :now,
                        status = 'approved'
                """),
                {
                    "root_url": meta["root_url"],
                    "domain": meta["domain"],
                    "query": meta.get("query"),
                    "classification": str(meta.get("llm_classification")),
                    "max_rate": max_crawl_rate,
                    "now": now,
                },
            )
            session.commit()
            logger.info("Approved site: %s (max rate: %.2f req/s)", meta["root_url"], max_crawl_rate)
        except Exception as e:
            session.rollback()
            logger.error("Failed to save site %s: %s", meta["root_url"], e)
        finally:
            session.close()

    def handle_error(self, failure):
        logger.debug("Request failed: %s", failure.value)

    def close_spider(self, spider):
        if hasattr(self, '_engine'):
            self._engine.dispose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_discovery.py -v`

Expected: PASS

- [ ] **Step 5: Write test for 429 handling during probe**

Append to `tests/test_discovery.py`:

```python
def test_probe_levels_defined():
    from heimdall_crawler.spiders.discovery import PROBE_LEVELS
    assert len(PROBE_LEVELS) == 4
    # Verify escalating speed: delays should decrease
    delays = [level[0] for level in PROBE_LEVELS]
    assert delays == sorted(delays, reverse=True)


def test_search_templates_exist():
    from heimdall_crawler.spiders.discovery import SEARCH_TEMPLATES
    assert len(SEARCH_TEMPLATES) >= 3
    for template in SEARCH_TEMPLATES:
        assert "{state_name}" in template
```

- [ ] **Step 6: Run all discovery tests**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_discovery.py -v`

Expected: All tests PASS

- [ ] **Step 7: Commit**

```bash
git add crawler/heimdall_crawler/spiders/discovery.py tests/test_discovery.py
git commit -m "feat: add DiscoverySpider for search-based site discovery and probing"
```

---

## Task 5: Extraction Spider (Phase 3)

**Files:**
- Create: `crawler/heimdall_crawler/spiders/extraction.py`
- Test: `tests/test_extraction.py`

- [ ] **Step 1: Write failing tests for structured data extraction**

Create `tests/test_extraction.py`:

```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.spiders.extraction import (
    extract_json_ld,
    extract_open_graph,
    extract_next_data,
)
from unittest.mock import MagicMock
import json


def _make_response(html):
    resp = MagicMock()
    resp.text = html
    resp.url = "https://example.com/listing/1"
    # Use scrapy Selector-like interface
    from scrapy.http import HtmlResponse
    return HtmlResponse(url="https://example.com/listing/1", body=html.encode(), encoding="utf-8")


def test_extract_json_ld_real_estate():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "RealEstateListing", "name": "123 Main St", "price": "450000",
     "address": {"streetAddress": "123 Main St", "addressLocality": "Austin",
     "addressRegion": "TX", "postalCode": "78701"},
     "floorSize": {"value": "1800"}}
    </script>
    </head><body></body></html>
    """
    resp = _make_response(html)
    result = extract_json_ld(resp)
    assert result is not None
    assert result["address"] == "123 Main St"
    assert result["price"] == "450000"


def test_extract_json_ld_no_data():
    html = "<html><body><p>Hello world</p></body></html>"
    resp = _make_response(html)
    result = extract_json_ld(resp)
    assert result is None


def test_extract_next_data():
    data = {
        "props": {
            "pageProps": {
                "listings": [
                    {"price": 450000, "address": "123 Main St", "sqft": 1800}
                ]
            }
        }
    }
    html = f'<html><head></head><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'
    resp = _make_response(html)
    result = extract_next_data(resp)
    assert result is not None
    assert len(result) >= 1


def test_extract_next_data_no_script():
    html = "<html><body><p>No next data</p></body></html>"
    resp = _make_response(html)
    result = extract_next_data(resp)
    assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_extraction.py -v`

Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Implement ExtractionSpider**

Create `crawler/heimdall_crawler/spiders/extraction.py`:

```python
import json
import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy
from scrapy.exceptions import CloseSpider
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from heimdall_crawler.antibot import detect_antibot
from heimdall_crawler.items import ListingItem
from heimdall_crawler.llm import generate_selectors

logger = logging.getLogger(__name__)

# URL patterns that suggest listing pages
LISTING_PATH_PATTERNS = [
    "/listing", "/property", "/for-sale", "/for-rent",
    "/rent", "/buy", "/homes", "/apartments", "/real-estate",
    "/house", "/condo",
]

MAX_DEPTH = 3
MAX_PAGES_PER_SITE = 200


def extract_json_ld(response):
    """Try to extract real estate data from JSON-LD structured data."""
    scripts = response.css('script[type="application/ld+json"]::text').getall()
    for script_text in scripts:
        try:
            data = json.loads(script_text)
        except json.JSONDecodeError:
            continue

        # Handle @graph arrays
        if isinstance(data, dict) and "@graph" in data:
            data = data["@graph"]
        if isinstance(data, list):
            for item in data:
                result = _parse_json_ld_item(item)
                if result:
                    return result
        elif isinstance(data, dict):
            result = _parse_json_ld_item(data)
            if result:
                return result

    return None


def _parse_json_ld_item(data):
    """Parse a single JSON-LD item for real estate fields."""
    item_type = data.get("@type", "")
    real_estate_types = ["RealEstateListing", "Product", "Residence", "House", "Apartment", "SingleFamilyResidence"]

    if isinstance(item_type, list):
        matches = any(t in real_estate_types for t in item_type)
    else:
        matches = item_type in real_estate_types

    if not matches:
        return None

    result = {}
    result["price"] = data.get("price") or data.get("offers", {}).get("price")

    address = data.get("address", {})
    if isinstance(address, dict):
        result["address"] = address.get("streetAddress", "")
        result["city"] = address.get("addressLocality", "")
        result["region"] = address.get("addressRegion", "")
        result["postal_code"] = address.get("postalCode", "")
    elif isinstance(address, str):
        result["address"] = address

    floor_size = data.get("floorSize", {})
    if isinstance(floor_size, dict):
        result["sqft"] = floor_size.get("value")
    elif floor_size:
        result["sqft"] = str(floor_size)

    result["bedrooms"] = data.get("numberOfRooms") or data.get("numberOfBedrooms")

    if result.get("address") or result.get("price"):
        return result
    return None


def extract_open_graph(response):
    """Try to extract listing data from Open Graph meta tags."""
    og_type = response.css('meta[property="og:type"]::attr(content)').get("")
    if "real_estate" not in og_type.lower() and "product" not in og_type.lower():
        return None

    result = {}
    result["address"] = response.css('meta[property="og:title"]::attr(content)').get("")
    price_str = response.css('meta[property="product:price:amount"]::attr(content)').get()
    if price_str:
        result["price"] = price_str

    if result.get("address") or result.get("price"):
        return result
    return None


def extract_next_data(response):
    """Try to extract listing data from __NEXT_DATA__ script tag."""
    script = response.css('script#__NEXT_DATA__::text').get()
    if not script:
        return None

    try:
        data = json.loads(script)
    except json.JSONDecodeError:
        return None

    # Recursively search for arrays that look like listings
    listings = _find_listing_arrays(data)
    return listings if listings else None


def _find_listing_arrays(obj, depth=0):
    """Recursively search for arrays containing listing-like objects."""
    if depth > 8:
        return None

    if isinstance(obj, list) and len(obj) > 0:
        # Check if items look like listings (have price or address)
        if isinstance(obj[0], dict):
            has_listing_keys = any(
                k in obj[0] for k in ["price", "address", "listPrice", "listingPrice", "streetAddress"]
            )
            if has_listing_keys:
                return obj

    if isinstance(obj, dict):
        for key in ["listings", "properties", "results", "searchResults", "homes", "items"]:
            if key in obj:
                found = _find_listing_arrays(obj[key], depth + 1)
                if found:
                    return found
        # Search all values
        for value in obj.values():
            if isinstance(value, (dict, list)):
                found = _find_listing_arrays(value, depth + 1)
                if found:
                    return found

    return None


class ExtractionSpider(scrapy.Spider):
    """Phase 3: Extract listing data from approved sites.

    Usage:
        scrapy crawl extraction
    """

    name = "extraction"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selectors_cache = {}  # site_id -> {selectors, structured_data_type}
        self._pages_per_site = {}   # domain -> count
        self._api_key = None
        self._failed_extractions = {}  # site_id -> count of empty results

    def start_requests(self):
        db_url = self.settings.get("DATABASE_URL", "postgresql://heimdall:heimdall@localhost:5433/heimdall")
        self._api_key = self.settings.get("LLM_API_KEY", "")

        engine = create_engine(db_url)
        Session = sessionmaker(bind=engine)
        self._db_session_factory = Session
        self._engine = engine

        # Load approved sites
        session = Session()
        try:
            sites = session.execute(
                text("SELECT id, root_url, domain, max_crawl_rate FROM discovered_sites WHERE status = 'approved'")
            ).fetchall()
        finally:
            session.close()

        if not sites:
            logger.info("No approved sites to extract from")
            return

        # Load cached selectors
        session = Session()
        try:
            selectors = session.execute(
                text("SELECT site_id, selectors, structured_data_type FROM extraction_selectors")
            ).fetchall()
            for row in selectors:
                self._selectors_cache[str(row[0])] = {
                    "selectors": json.loads(row[1]) if isinstance(row[1], str) else row[1],
                    "structured_data_type": row[2],
                }
        finally:
            session.close()

        logger.info("Loaded %d approved sites, %d cached selectors", len(sites), len(self._selectors_cache))

        for site_id, root_url, domain, max_crawl_rate in sites:
            delay = 1.0 / max_crawl_rate if max_crawl_rate and max_crawl_rate > 0 else 5
            self._pages_per_site[domain] = 0
            yield scrapy.Request(
                root_url,
                callback=self.parse_page,
                meta={
                    "site_id": str(site_id),
                    "domain": domain,
                    "root_url": root_url,
                    "depth": 0,
                    "download_delay": delay,
                },
                errback=self.handle_error,
            )

    def parse_page(self, response):
        """Extract listings and follow links."""
        meta = response.meta
        domain = meta["domain"]
        site_id = meta["site_id"]
        depth = meta.get("depth", 0)

        # Check page budget
        self._pages_per_site[domain] = self._pages_per_site.get(domain, 0) + 1
        if self._pages_per_site[domain] > MAX_PAGES_PER_SITE:
            return

        # Check for antibot
        if detect_antibot(response):
            logger.warning("Antibot detected on %s during extraction — marking blocked", domain)
            self._mark_site_blocked(site_id)
            return

        # Try to extract listings
        items = self._extract_listings(response, site_id, domain)
        for item in items:
            yield item

        # Follow links if under depth limit
        if depth < MAX_DEPTH:
            for link in self._find_listing_links(response):
                full_url = response.urljoin(link)
                if urlparse(full_url).netloc == domain:
                    yield scrapy.Request(
                        full_url,
                        callback=self.parse_page,
                        meta={
                            **meta,
                            "depth": depth + 1,
                        },
                        errback=self.handle_error,
                    )

    def _extract_listings(self, response, site_id, domain):
        """Try structured data first, then cached selectors, then LLM-generated selectors."""
        items = []

        # 1. Check cached selectors
        cached = self._selectors_cache.get(site_id)
        if cached:
            if cached.get("structured_data_type"):
                items = self._extract_with_structured(response, cached["structured_data_type"])
            elif cached.get("selectors"):
                items = self._extract_with_selectors(response, cached["selectors"], domain)

            if items:
                return items
            else:
                # Track failures for selector staleness
                self._failed_extractions[site_id] = self._failed_extractions.get(site_id, 0) + 1
                if self._failed_extractions[site_id] > 10:
                    # Selectors are stale — try regenerating
                    self._selectors_cache.pop(site_id, None)

        # 2. Try structured data detection
        json_ld = extract_json_ld(response)
        if json_ld:
            self._cache_selector(site_id, "json-ld", None)
            return [self._make_item(json_ld, domain, response.url)]

        og = extract_open_graph(response)
        if og:
            self._cache_selector(site_id, "open-graph", None)
            return [self._make_item(og, domain, response.url)]

        next_data = extract_next_data(response)
        if next_data:
            self._cache_selector(site_id, "next-data", None)
            for listing in next_data[:50]:  # Cap per page
                item = self._make_item(listing, domain, response.url)
                if item:
                    items.append(item)
            return items

        # 3. LLM fallback — generate selectors
        if self._api_key:
            selectors = generate_selectors(
                response.text[:6000],
                api_key=self._api_key,
                base_url=self.settings.get("LLM_BASE_URL", "https://api.deepseek.com/v1"),
                model=self.settings.get("LLM_MODEL", "deepseek-v3.2"),
                timeout=self.settings.getint("LLM_TIMEOUT", 30),
            )
            if selectors:
                self._cache_selector(site_id, None, selectors)
                items = self._extract_with_selectors(response, selectors, domain)
                return items

        return []

    def _extract_with_structured(self, response, data_type):
        """Extract using a known structured data type."""
        if data_type == "json-ld":
            result = extract_json_ld(response)
            return [self._make_item(result, "", response.url)] if result else []
        elif data_type == "open-graph":
            result = extract_open_graph(response)
            return [self._make_item(result, "", response.url)] if result else []
        elif data_type == "next-data":
            results = extract_next_data(response)
            if results:
                return [self._make_item(r, "", response.url) for r in results[:50] if r]
        return []

    def _extract_with_selectors(self, response, selectors, domain):
        """Extract listing data using CSS selectors."""
        items = []
        # Try to find repeating listing containers
        # Use the most specific selector to find listing items
        data = {}
        for field, selector in selectors.items():
            values = response.css(f"{selector}::text").getall()
            if values:
                data[field] = values

        if not data:
            return []

        # Zip extracted fields into individual listings
        max_items = max(len(v) for v in data.values()) if data else 0
        for i in range(min(max_items, 50)):
            listing = {}
            for field, values in data.items():
                if i < len(values):
                    listing[field] = values[i].strip()
            item = self._make_item(listing, domain, response.url)
            if item:
                items.append(item)

        return items

    def _make_item(self, data, domain, source_url):
        """Convert extracted data dict into a ListingItem."""
        if not data:
            return None
        if not data.get("price") and not data.get("address"):
            return None

        item = ListingItem()
        item["source"] = domain or urlparse(source_url).netloc
        item["address"] = data.get("address") or data.get("streetAddress") or ""
        item["price"] = data.get("price") or data.get("listPrice") or data.get("listingPrice")
        item["sqft"] = data.get("sqft") or data.get("floorSize") or data.get("livingArea")
        item["city"] = data.get("city") or data.get("addressLocality") or ""
        item["region"] = data.get("region") or data.get("addressRegion") or data.get("state") or ""
        item["postal_code"] = data.get("postal_code") or data.get("postalCode") or data.get("zipCode") or ""
        item["country"] = data.get("country") or "US"
        item["source_url"] = source_url
        item["published_at"] = None

        # Determine listing type from context
        listing_type = data.get("listing_type") or data.get("listingType") or ""
        if any(kw in str(listing_type).lower() for kw in ["rent", "lease", "apartment"]):
            item["listing_type"] = "rent"
        else:
            item["listing_type"] = "buy"

        return item

    def _cache_selector(self, site_id, structured_data_type, selectors):
        """Cache extraction method in DB and memory."""
        self._selectors_cache[site_id] = {
            "selectors": selectors,
            "structured_data_type": structured_data_type,
        }

        session = self._db_session_factory()
        try:
            now = datetime.now(timezone.utc)
            selectors_json = json.dumps(selectors) if selectors else None
            method = structured_data_type or "llm"
            session.execute(
                text("""
                    INSERT INTO extraction_selectors (id, site_id, page_pattern, selectors,
                        structured_data_type, created_at, validated_at)
                    VALUES (gen_random_uuid(), :site_id, '*', :selectors,
                        :structured_type, :now, :now)
                    ON CONFLICT (site_id, page_pattern)
                    DO UPDATE SET selectors = :selectors, structured_data_type = :structured_type,
                        validated_at = :now
                """),
                {
                    "site_id": site_id,
                    "selectors": selectors_json,
                    "structured_type": structured_data_type,
                    "now": now,
                },
            )
            # Also update extraction_method on the site
            session.execute(
                text("UPDATE discovered_sites SET extraction_method = :method, last_extracted_at = :now WHERE id = :id"),
                {"method": method, "now": now, "id": site_id},
            )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to cache selectors for site %s: %s", site_id, e)
        finally:
            session.close()

    def _mark_site_blocked(self, site_id):
        """Mark a site as blocked in the DB."""
        session = self._db_session_factory()
        try:
            session.execute(
                text("UPDATE discovered_sites SET status = 'blocked' WHERE id = :id"),
                {"id": site_id},
            )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to mark site blocked: %s", e)
        finally:
            session.close()

    def _find_listing_links(self, response):
        """Find links that likely lead to listing pages."""
        links = []
        for href in response.css("a::attr(href)").getall():
            href_lower = href.lower()
            if any(pattern in href_lower for pattern in LISTING_PATH_PATTERNS):
                links.append(href)
            # Pagination links (page=N, ?p=N, /page/N)
            elif "page" in href_lower or "?p=" in href_lower:
                links.append(href)
        return links[:30]  # Cap links per page

    def handle_error(self, failure):
        logger.debug("Request failed: %s", failure.value)

    def close_spider(self, spider):
        if hasattr(self, '_engine'):
            self._engine.dispose()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_extraction.py -v`

Expected: All 4 tests PASS

- [ ] **Step 5: Write additional test for selector-based extraction**

Append to `tests/test_extraction.py`:

```python
def test_extract_open_graph():
    html = """
    <html><head>
    <meta property="og:type" content="real_estate.listing" />
    <meta property="og:title" content="456 Oak Ave, Dallas, TX" />
    <meta property="product:price:amount" content="350000" />
    </head><body></body></html>
    """
    resp = _make_response(html)
    result = extract_open_graph(resp)
    assert result is not None
    assert result["price"] == "350000"


def test_extract_open_graph_no_type():
    html = """
    <html><head>
    <meta property="og:type" content="website" />
    </head><body></body></html>
    """
    resp = _make_response(html)
    result = extract_open_graph(resp)
    assert result is None
```

- [ ] **Step 6: Run all extraction tests**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_extraction.py -v`

Expected: All 6 tests PASS

- [ ] **Step 7: Commit**

```bash
git add crawler/heimdall_crawler/spiders/extraction.py tests/test_extraction.py
git commit -m "feat: add ExtractionSpider for generic listing extraction from approved sites"
```

---

## Task 6: Rewrite run_all.py Orchestration

**Files:**
- Modify: `crawler/run_all.py`
- Test: Manual verification

- [ ] **Step 1: Rewrite run_all.py**

Replace the entire content of `crawler/run_all.py`:

```python
#!/usr/bin/env python
"""Run crawler in discover, extract, or combined mode.

Usage:
    python run_all.py discover [--regions TX CA FL]   # Phase 1+2: find new sites
    python run_all.py extract  [--regions TX CA FL]   # Phase 3: extract from approved sites
    python run_all.py all      [--regions TX CA FL]   # Both in sequence
"""
import argparse
import subprocess
import sys


DEFAULT_REGIONS = ["TX"]


def run_spider(spider, args=None):
    """Run a Scrapy spider as a subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", "scrapy", "crawl", spider]
    if args:
        for key, value in args.items():
            cmd.extend(["-a", f"{key}={value}"])

    print(f"\n{'='*60}")
    print(f"Running: {spider} {args or ''}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=".")
    if result.returncode != 0:
        print(f"WARNING: {spider} exited with code {result.returncode}")
        return False
    return True


def discover(regions):
    """Phase 1+2: Discover and probe new real estate websites."""
    run_spider("discovery", {"regions": ",".join(regions)})


def extract(regions):
    """Phase 3: Extract data from approved sites + Numbeo."""
    # Run Numbeo (reliable aggregate source)
    run_spider("numbeo")

    # Run generic extraction against all approved sites
    run_spider("extraction")


def main():
    parser = argparse.ArgumentParser(description="Heimdall crawler orchestration")
    parser.add_argument("mode", choices=["discover", "extract", "all"],
                        help="discover: find new sites, extract: scrape approved sites, all: both")
    parser.add_argument("--regions", nargs="+", default=DEFAULT_REGIONS,
                        help="US state abbreviations (default: TX)")
    args = parser.parse_args()

    if args.mode in ("discover", "all"):
        discover(args.regions)

    if args.mode in ("extract", "all"):
        extract(args.regions)

    print(f"\n{'='*60}")
    print(f"Crawl complete (mode: {args.mode}).")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify help text works**

Run: `cd /Users/yourstruly/Documents/heimdall/crawler && python run_all.py --help`

Expected: Shows usage with discover/extract/all modes and --regions option.

- [ ] **Step 3: Commit**

```bash
git add crawler/run_all.py
git commit -m "feat: rewrite run_all.py with discover/extract/all orchestration modes"
```

---

## Task 7: Remove Blocked Spiders

**Files:**
- Remove: `crawler/heimdall_crawler/spiders/realtor.py`
- Remove: `crawler/heimdall_crawler/spiders/redfin.py`
- Remove: `crawler/heimdall_crawler/spiders/zillow.py`

- [ ] **Step 1: Remove the three blocked spider files**

```bash
cd /Users/yourstruly/Documents/heimdall
git rm crawler/heimdall_crawler/spiders/realtor.py
git rm crawler/heimdall_crawler/spiders/redfin.py
git rm crawler/heimdall_crawler/spiders/zillow.py
```

- [ ] **Step 2: Run existing tests to ensure nothing breaks**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/ -v --ignore=tests/test_enrichment.py --ignore=tests/test_region_metrics.py`

Expected: All tests PASS (no tests imported the removed spiders)

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "chore: remove blocked realtor, redfin, and zillow spiders"
```

---

## Task 8: Add Unique Constraint for Extraction Selectors

The `extraction_selectors` table needs a unique constraint on `(site_id, page_pattern)` for the ON CONFLICT clause in ExtractionSpider's `_cache_selector` method to work.

**Files:**
- Modify: `backend/app/models.py`
- Create: Alembic migration (auto-generated)

- [ ] **Step 1: Add UniqueConstraint to ExtractionSelector model**

In `backend/app/models.py`, update `ExtractionSelector.__table_args__`:

```python
    __table_args__ = (
        UniqueConstraint("site_id", "page_pattern", name="uq_selector_site_pattern"),
        Index("ix_extraction_selectors_site_id", "site_id"),
    )
```

- [ ] **Step 2: Generate and apply migration**

```bash
cd /Users/yourstruly/Documents/heimdall/backend
alembic revision --autogenerate -m "add unique constraint to extraction_selectors"
alembic upgrade head
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models.py backend/alembic/versions/
git commit -m "feat: add unique constraint on extraction_selectors(site_id, page_pattern)"
```

---

## Task 9: Run Full Test Suite and Verify

- [ ] **Step 1: Run all unit tests**

Run: `cd /Users/yourstruly/Documents/heimdall && python -m pytest tests/test_llm.py tests/test_antibot.py tests/test_discovery.py tests/test_extraction.py tests/test_pipelines.py tests/test_models.py -v`

Expected: All tests PASS

- [ ] **Step 2: Verify spider registration**

Run: `cd /Users/yourstruly/Documents/heimdall/crawler && python -m scrapy list`

Expected output:
```
discovery
extraction
numbeo
```

(realtor, redfin, zillow should NOT appear)

- [ ] **Step 3: Verify settings have LLM config**

Run: `cd /Users/yourstruly/Documents/heimdall && python -c "from heimdall_crawler.settings import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL; print(f'LLM config: {LLM_BASE_URL} / {LLM_MODEL}')"`

Expected: `LLM config: https://api.deepseek.com/v1 / deepseek-v3.2`

- [ ] **Step 4: Commit any remaining changes**

If any fixes were needed, commit them:

```bash
git add -A
git commit -m "fix: address test suite issues from crawler redesign"
```
