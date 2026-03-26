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

LISTING_PATH_PATTERNS = [
    "/listing", "/property", "/for-sale", "/for-rent", "/rent",
    "/buy", "/homes", "/apartments", "/real-estate", "/house", "/condo",
]

MAX_DEPTH = 3
MAX_PAGES_PER_SITE = 200

# JSON-LD types that indicate real estate data
_REAL_ESTATE_TYPES = {
    "RealEstateListing", "Product", "Residence", "House",
    "Apartment", "SingleFamilyResidence",
}

# Keys that suggest an array contains listing objects
_LISTING_ARRAY_KEYS = {
    "listings", "properties", "results", "searchResults", "homes", "items",
}

# Keys that suggest an object is a listing
_LISTING_OBJECT_KEYS = {"price", "address", "listPrice", "salePrice", "rentPrice"}


# ---------------------------------------------------------------------------
# Module-level extraction functions (standalone for testability)
# ---------------------------------------------------------------------------

def _parse_json_ld_item(data):
    """Parse a single JSON-LD item if its @type matches real estate types.

    Returns a normalized dict with price, address, city, region, postal_code,
    sqft, bedrooms — or None if the type doesn't match.
    """
    item_type = data.get("@type", "")
    if isinstance(item_type, list):
        matching = any(t in _REAL_ESTATE_TYPES for t in item_type)
    else:
        matching = item_type in _REAL_ESTATE_TYPES
    if not matching:
        return None

    result = {}

    # Price
    price = data.get("price") or data.get("offers", {}).get("price")
    if price is not None:
        result["price"] = str(price)

    # Address
    addr = data.get("address", {})
    if isinstance(addr, dict):
        result["address"] = addr.get("streetAddress", "")
        result["city"] = addr.get("addressLocality", "")
        result["region"] = addr.get("addressRegion", "")
        result["postal_code"] = addr.get("postalCode", "")
    elif isinstance(addr, str):
        result["address"] = addr

    # Square footage
    floor_size = data.get("floorSize")
    if isinstance(floor_size, dict):
        result["sqft"] = floor_size.get("value", "")
    elif floor_size is not None:
        result["sqft"] = str(floor_size)

    # Bedrooms
    bedrooms = data.get("numberOfBedrooms") or data.get("numberOfRooms")
    if bedrooms is not None:
        result["bedrooms"] = str(bedrooms)

    return result if result else None


def extract_json_ld(response):
    """Extract real estate data from <script type="application/ld+json"> tags.

    Handles @graph arrays. Returns a dict of extracted fields or None.
    """
    scripts = response.css('script[type="application/ld+json"]::text').getall()
    for script_text in scripts:
        try:
            data = json.loads(script_text)
        except (json.JSONDecodeError, TypeError):
            continue

        # Handle @graph arrays
        items = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            if "@graph" in data:
                items = data["@graph"] if isinstance(data["@graph"], list) else [data["@graph"]]
            else:
                items = [data]

        for item in items:
            if not isinstance(item, dict):
                continue
            result = _parse_json_ld_item(item)
            if result is not None:
                return result

    return None


def extract_open_graph(response):
    """Extract listing data from Open Graph meta tags.

    Only returns data if og:type contains 'real_estate' or 'product'.
    Returns a dict with title and price, or None.
    """
    og_type = response.css('meta[property="og:type"]::attr(content)').get("")
    if not og_type:
        return None

    og_type_lower = og_type.lower()
    if "real_estate" not in og_type_lower and "product" not in og_type_lower:
        return None

    result = {}

    title = response.css('meta[property="og:title"]::attr(content)').get()
    if title:
        result["title"] = title

    # Try multiple price meta tag patterns
    price = (
        response.css('meta[property="product:price:amount"]::attr(content)').get()
        or response.css('meta[property="og:price:amount"]::attr(content)').get()
        or response.css('meta[property="price:amount"]::attr(content)').get()
    )
    if price:
        result["price"] = price

    return result if result else None


def _find_listing_arrays(obj, depth=0):
    """Recursively search for arrays containing listing-like objects.

    Capped at depth 8. Returns the first matching list of dicts found,
    or None.
    """
    if depth > 8:
        return None

    if isinstance(obj, dict):
        # Check known listing-array keys first
        for key in _LISTING_ARRAY_KEYS:
            if key in obj:
                val = obj[key]
                if isinstance(val, list) and val and isinstance(val[0], dict):
                    # Check if items look like listings
                    if any(k in val[0] for k in _LISTING_OBJECT_KEYS):
                        return val
        # Recurse into all values
        for val in obj.values():
            result = _find_listing_arrays(val, depth + 1)
            if result is not None:
                return result
    elif isinstance(obj, list):
        # Check if this list itself contains listing objects
        if obj and isinstance(obj[0], dict):
            if any(k in obj[0] for k in _LISTING_OBJECT_KEYS):
                return obj
        for item in obj:
            result = _find_listing_arrays(item, depth + 1)
            if result is not None:
                return result

    return None


def extract_next_data(response):
    """Extract listing data from Next.js __NEXT_DATA__ script tag.

    Returns a list of listing dicts, or None.
    """
    script = response.css('script#__NEXT_DATA__::text').get()
    if not script:
        return None

    try:
        data = json.loads(script)
    except (json.JSONDecodeError, TypeError):
        return None

    return _find_listing_arrays(data)


# ---------------------------------------------------------------------------
# ExtractionSpider
# ---------------------------------------------------------------------------

class ExtractionSpider(scrapy.Spider):
    name = "extraction"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._selectors_cache = {}   # site_id -> {"selectors": dict, "structured_data_type": str}
        self._pages_per_site = {}    # site_id -> count
        self._api_key = ""
        self._failed_extractions = {}  # site_id -> count
        self._engine = None
        self._Session = None

    def start_requests(self):
        self._api_key = self.settings.get("LLM_API_KEY", "")

        db_url = self.settings.get(
            "DATABASE_URL", "postgresql://heimdall:heimdall@localhost:5433/heimdall"
        )
        self._engine = create_engine(db_url)
        self._Session = sessionmaker(bind=self._engine)

        # Load approved sites
        session = self._Session()
        try:
            sites = session.execute(
                text("""
                    SELECT id, root_url, domain, max_crawl_rate
                    FROM discovered_sites
                    WHERE status = 'approved'
                """)
            ).fetchall()
        except Exception as e:
            logger.error("Failed to load approved sites: %s", e)
            raise CloseSpider("Cannot load approved sites from DB")
        finally:
            session.close()

        if not sites:
            logger.warning("No approved sites found in discovered_sites")
            return

        # Load cached selectors
        self._load_cached_selectors()

        for site in sites:
            site_id, root_url, domain, max_crawl_rate = site
            delay = 1.0 / max_crawl_rate if max_crawl_rate and max_crawl_rate > 0 else 5.0
            self._pages_per_site[str(site_id)] = 0
            yield scrapy.Request(
                root_url,
                callback=self.parse_page,
                errback=self.handle_error,
                meta={
                    "site_id": str(site_id),
                    "domain": domain,
                    "depth": 0,
                    "download_delay": delay,
                },
            )

    def _load_cached_selectors(self):
        """Load extraction selectors from the DB into memory cache."""
        session = self._Session()
        try:
            rows = session.execute(
                text("""
                    SELECT site_id, structured_data_type, selectors
                    FROM extraction_selectors
                """)
            ).fetchall()
            for row in rows:
                site_id, structured_data_type, selectors = row
                self._selectors_cache[str(site_id)] = {
                    "structured_data_type": structured_data_type,
                    "selectors": json.loads(selectors) if isinstance(selectors, str) else selectors,
                }
            logger.info("Loaded %d cached selector sets", len(self._selectors_cache))
        except Exception as e:
            logger.warning("Could not load extraction_selectors: %s", e)
        finally:
            session.close()

    def parse_page(self, response):
        """Parse a page: check budget, detect antibot, extract listings, follow links."""
        site_id = response.meta["site_id"]
        domain = response.meta["domain"]
        depth = response.meta.get("depth", 0)

        # Check page budget
        count = self._pages_per_site.get(site_id, 0)
        if count >= MAX_PAGES_PER_SITE:
            logger.debug("Page budget exhausted for site %s", site_id)
            return
        self._pages_per_site[site_id] = count + 1

        # Check antibot
        if detect_antibot(response):
            logger.warning("Antibot detected on %s, marking site blocked", domain)
            self._mark_site_blocked(site_id)
            return

        # Extract listings
        listings = self._extract_listings(response, site_id, domain)
        for listing in listings:
            yield listing

        # Follow links if under depth limit
        if depth < MAX_DEPTH:
            for link in self._find_listing_links(response):
                yield scrapy.Request(
                    link,
                    callback=self.parse_page,
                    errback=self.handle_error,
                    meta={
                        "site_id": site_id,
                        "domain": domain,
                        "depth": depth + 1,
                        "download_delay": response.meta.get("download_delay", 5.0),
                    },
                )

    def _extract_listings(self, response, site_id, domain):
        """Try cached selectors, then structured data, then LLM fallback."""
        items = []

        # 1. Try cached selectors
        cached = self._selectors_cache.get(site_id)
        if cached:
            method = cached["structured_data_type"]
            if method in ("json_ld", "open_graph", "next_data"):
                data = self._extract_with_structured(response, method)
                if data:
                    if isinstance(data, list):
                        for d in data:
                            item = self._make_item(d, domain, response.url)
                            if item:
                                items.append(item)
                    else:
                        item = self._make_item(data, domain, response.url)
                        if item:
                            items.append(item)
                    return items
            elif method == "css_selectors":
                selectors = cached.get("selectors", {})
                items = self._extract_with_selectors(response, selectors, domain)
                if items:
                    return items

        # 2. Try structured data extractors
        for data_type in ("json_ld", "open_graph", "next_data"):
            data = self._extract_with_structured(response, data_type)
            if data:
                if isinstance(data, list):
                    for d in data:
                        item = self._make_item(d, domain, response.url)
                        if item:
                            items.append(item)
                else:
                    item = self._make_item(data, domain, response.url)
                    if item:
                        items.append(item)
                if items:
                    self._cache_selector(site_id, data_type, None)
                    return items

        # 3. LLM fallback — generate CSS selectors
        if self._api_key:
            base_url = self.settings.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
            model = self.settings.get("LLM_MODEL", "deepseek-v3.2")
            timeout = self.settings.getint("LLM_TIMEOUT", 30)
            selectors = generate_selectors(
                response.text[:6000], self._api_key, base_url, model, timeout
            )
            if selectors:
                items = self._extract_with_selectors(response, selectors, domain)
                if items:
                    self._cache_selector(site_id, "css_selectors", selectors)
                    return items

        # Track failed extractions
        self._failed_extractions[site_id] = self._failed_extractions.get(site_id, 0) + 1
        return items

    def _extract_with_structured(self, response, data_type):
        """Dispatch to the correct structured data extractor."""
        if data_type == "json_ld":
            return extract_json_ld(response)
        elif data_type == "open_graph":
            return extract_open_graph(response)
        elif data_type == "next_data":
            return extract_next_data(response)
        return None

    def _extract_with_selectors(self, response, selectors, domain):
        """Use CSS selectors to extract listing data. Returns list of ListingItem."""
        if not selectors:
            return []

        # Extract each field as a list of values
        field_values = {}
        max_len = 0
        for field, selector in selectors.items():
            try:
                values = response.css(f"{selector}::text").getall()
                field_values[field] = values
                if len(values) > max_len:
                    max_len = len(values)
            except Exception:
                field_values[field] = []

        if max_len == 0:
            return []

        # Zip fields into listings, capped at 50 per page
        items = []
        for i in range(min(max_len, 50)):
            data = {}
            for field, values in field_values.items():
                if i < len(values):
                    data[field] = values[i].strip()
            item = self._make_item(data, domain, response.url)
            if item:
                items.append(item)
        return items

    def _make_item(self, data, domain, source_url):
        """Convert an extracted dict to a ListingItem.

        Returns None if there is no price and no address.
        """
        if not data:
            return None

        price = data.get("price")
        address = data.get("address") or data.get("title", "")

        if not price and not address:
            return None

        item = ListingItem()
        item["source"] = domain or urlparse(source_url).netloc
        item["source_url"] = source_url
        item["price"] = price or ""
        item["address"] = address

        # Determine listing type from URL or data context
        listing_type = data.get("listing_type", "")
        if not listing_type:
            url_lower = source_url.lower()
            if any(kw in url_lower for kw in ("/rent", "/for-rent", "/apartments")):
                listing_type = "rent"
            else:
                listing_type = "buy"
        item["listing_type"] = listing_type

        item["city"] = data.get("city", "")
        item["region"] = data.get("region", "")
        item["postal_code"] = data.get("postal_code", "")
        item["country"] = data.get("country", "")
        item["sqft"] = data.get("sqft", "")
        item["published_at"] = None

        return item

    def _cache_selector(self, site_id, structured_data_type, selectors):
        """Save extraction method to DB and memory cache."""
        # Update memory cache
        self._selectors_cache[site_id] = {
            "structured_data_type": structured_data_type,
            "selectors": selectors or {},
        }

        if not self._Session:
            return

        now = datetime.now(timezone.utc)
        session = self._Session()
        try:
            selectors_json = json.dumps(selectors) if selectors else "{}"
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
            # Update discovered_sites metadata
            session.execute(
                text("""
                    UPDATE discovered_sites
                    SET extraction_method = :method, last_extracted_at = :now
                    WHERE id = :site_id
                """),
                {
                    "method": structured_data_type,
                    "site_id": site_id,
                    "now": now,
                },
            )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to cache selector for site %s: %s", site_id, e)
        finally:
            session.close()

    def _mark_site_blocked(self, site_id):
        """Mark a site as blocked in the DB."""
        if not self._Session:
            return

        session = self._Session()
        try:
            session.execute(
                text("UPDATE discovered_sites SET status = 'blocked' WHERE id = :site_id"),
                {"site_id": site_id},
            )
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error("Failed to mark site %s blocked: %s", site_id, e)
        finally:
            session.close()

    def _find_listing_links(self, response):
        """Find links matching listing path patterns and pagination, capped at 30."""
        links = []
        seen = set()
        parsed_base = urlparse(response.url)
        base_domain = parsed_base.netloc.lower()

        for href in response.css("a::attr(href)").getall():
            url = response.urljoin(href)
            parsed = urlparse(url)

            # Stay on the same domain
            if parsed.netloc.lower() != base_domain:
                continue

            if url in seen:
                continue

            path_lower = parsed.path.lower()
            # Match listing path patterns or pagination (?page=, /page/)
            is_listing = any(pat in path_lower for pat in LISTING_PATH_PATTERNS)
            is_pagination = "page" in path_lower or "page=" in (parsed.query or "").lower()

            if is_listing or is_pagination:
                seen.add(url)
                links.append(url)
                if len(links) >= 30:
                    break

        return links

    def handle_error(self, failure):
        """Log request failures."""
        logger.debug("Request failed: %s", failure.value)

    def close_spider(self, reason):
        """Dispose DB engine and log summary."""
        if self._failed_extractions:
            logger.info(
                "Failed extraction counts by site: %s",
                dict(self._failed_extractions),
            )
        if self._engine:
            self._engine.dispose()
