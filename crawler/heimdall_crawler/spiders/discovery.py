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

# (delay_seconds, num_requests) — starts slow, escalates
PROBE_LEVELS = [
    (10, 3),
    (5, 3),
    (2, 3),
    (1, 3),
]

SKIP_DOMAINS = {
    "google.com", "google.co", "googleapis.com", "gstatic.com",
    "youtube.com", "youtu.be",
    "wikipedia.org", "wikimedia.org",
    "facebook.com", "twitter.com", "instagram.com", "linkedin.com",
    "reddit.com", "pinterest.com", "tiktok.com",
    "amazon.com", "ebay.com",
    "yelp.com", "bbb.org",
}


class DiscoverySpider(scrapy.Spider):
    name = "discovery"

    def __init__(self, regions="TX", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.regions = [r.strip().upper() for r in regions.split(",") if r.strip()]
        self._known_domains = set()
        self._engine = None
        self._Session = None

    def _build_search_queries(self):
        """Generate search queries for all regions using SEARCH_TEMPLATES."""
        queries = []
        for region in self.regions:
            state_name = STATE_NAMES.get(region, region)
            for template in SEARCH_TEMPLATES:
                queries.append(template.format(state_name=state_name))
        return queries

    def start_requests(self):
        api_key = self.settings.get("LLM_API_KEY", "")
        if not api_key:
            raise CloseSpider("LLM_API_KEY is not set in settings")

        db_url = self.settings.get(
            "DATABASE_URL", "postgresql://heimdall:heimdall@localhost:5433/heimdall"
        )
        self._engine = create_engine(db_url)
        self._Session = sessionmaker(bind=self._engine)

        # Load known domains from discovered_sites
        session = self._Session()
        try:
            rows = session.execute(
                text("SELECT domain FROM discovered_sites")
            ).fetchall()
            for row in rows:
                self._known_domains.add(row[0].lower())
        except Exception as e:
            logger.warning("Could not load discovered_sites: %s", e)
        finally:
            session.close()

        queries = self._build_search_queries()
        for query in queries:
            search_url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            yield scrapy.Request(
                search_url,
                callback=self.parse_search_results,
                meta={
                    "query": query,
                    "playwright": True,
                    "playwright_include_page": False,
                },
                errback=self.handle_error,
            )

    def parse_search_results(self, response):
        """Extract links from Google search results rendered via Playwright."""
        # Playwright-rendered Google uses direct links in search result anchors.
        # Try multiple selectors to handle different Google result layouts.
        links = set()

        # Standard organic result links
        for a in response.css("div#search a[href]"):
            href = a.attrib.get("href", "")
            links.add(href)

        # Fallback: all links on page
        for href in response.css("a::attr(href)").getall():
            # Google redirect wrapper (non-Playwright fallback)
            if href.startswith("/url?q="):
                href = href.split("/url?q=")[1].split("&")[0]
            links.add(href)

        for link in links:
            parsed = urlparse(link)
            if not parsed.scheme or not parsed.netloc:
                continue

            domain = parsed.netloc.lower()
            bare_domain = domain.removeprefix("www.")

            if domain in self._known_domains or bare_domain in self._known_domains:
                continue

            if any(skip in bare_domain for skip in SKIP_DOMAINS):
                continue

            self._known_domains.add(bare_domain)
            yield scrapy.Request(
                link,
                callback=self.check_candidate,
                meta={
                    "root_url": f"{parsed.scheme}://{parsed.netloc}",
                    "query": response.meta.get("query"),
                },
                errback=self.handle_error,
            )

    def check_candidate(self, response):
        """Check if a candidate page contains real estate data."""
        if detect_antibot(response):
            logger.info("Antibot detected on candidate %s, skipping", response.url)
            return

        page_text = " ".join(response.css("body *::text").getall()).strip()
        if not page_text:
            return

        api_key = self.settings.get("LLM_API_KEY", "")
        base_url = self.settings.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
        model = self.settings.get("LLM_MODEL", "deepseek-v3.2")
        timeout = self.settings.getint("LLM_TIMEOUT", 30)

        result = llm_classify_page(page_text, api_key, base_url, model, timeout)
        if result and result.get("has_real_estate_data") and result.get("confidence", 0) >= 0.7:
            root_url = response.meta["root_url"]
            parsed_url = urlparse(response.url)
            domain = parsed_url.netloc.lower().removeprefix("www.")
            logger.info("Real estate data found on %s, starting probe", root_url)
            # Start escalating probe
            probe_links = self._collect_probe_links(response)
            if probe_links:
                yield scrapy.Request(
                    probe_links[0],
                    callback=self.probe_site,
                    dont_filter=True,
                    meta={
                        "root_url": root_url,
                        "domain": domain,
                        "query": response.meta.get("query"),
                        "probe_level": 0,
                        "probe_count": 0,
                        "probe_links": probe_links[1:],
                        "llm_classification": result,
                    },
                    errback=self.handle_error,
                )

    def probe_site(self, response):
        """Escalating speed probe. Tests site at increasing request rates."""
        if detect_antibot(response):
            level = response.meta["probe_level"]
            if level == 0:
                # Antibot at first probe level — abandon this site entirely
                logger.info(
                    "Antibot during probe of %s at level 0, abandoning",
                    response.meta["root_url"],
                )
                return
            # Site blocked us — save with previous level's rate as max
            max_delay = PROBE_LEVELS[level - 1][0]
            max_rate = 1.0 / max_delay
            logger.info(
                "Antibot during probe of %s at level %d, saving with rate=%.2f req/s",
                response.meta["root_url"], level, max_rate,
            )
            self._save_approved_site(response.meta, max_crawl_rate=max_rate)
            return

        level = response.meta["probe_level"]
        count = response.meta["probe_count"] + 1
        probe_links = response.meta.get("probe_links", [])

        _, num_requests = PROBE_LEVELS[level]

        if count >= num_requests:
            # Level complete, advance to next
            next_level = level + 1
            if next_level >= len(PROBE_LEVELS):
                # All levels passed — save with fastest rate
                max_delay = PROBE_LEVELS[-1][0]
                max_rate = 1.0 / max_delay
                logger.info(
                    "All probe levels passed for %s, saving with rate=%.2f req/s",
                    response.meta["root_url"], max_rate,
                )
                self._save_approved_site(response.meta, max_crawl_rate=max_rate)
                return

            # Collect more links for next level if needed
            if not probe_links:
                probe_links = self._collect_probe_links(response)

            if probe_links:
                delay = PROBE_LEVELS[next_level][0]
                yield scrapy.Request(
                    probe_links[0],
                    callback=self.probe_site,
                    dont_filter=True,
                    meta={
                        "root_url": response.meta["root_url"],
                        "domain": response.meta.get("domain"),
                        "query": response.meta.get("query"),
                        "probe_level": next_level,
                        "probe_count": 0,
                        "probe_links": probe_links[1:],
                        "llm_classification": response.meta.get("llm_classification"),
                        "download_delay": delay,
                    },
                    errback=self.handle_error,
                )
            else:
                # No more links to probe, save with current level's rate
                max_delay = PROBE_LEVELS[level][0]
                max_rate = 1.0 / max_delay
                self._save_approved_site(response.meta, max_crawl_rate=max_rate)
        else:
            # Continue at current level
            if not probe_links:
                probe_links = self._collect_probe_links(response)

            if probe_links:
                delay = PROBE_LEVELS[level][0]
                yield scrapy.Request(
                    probe_links[0],
                    callback=self.probe_site,
                    dont_filter=True,
                    meta={
                        "root_url": response.meta["root_url"],
                        "domain": response.meta.get("domain"),
                        "query": response.meta.get("query"),
                        "probe_level": level,
                        "probe_count": count,
                        "probe_links": probe_links[1:],
                        "llm_classification": response.meta.get("llm_classification"),
                        "download_delay": delay,
                    },
                    errback=self.handle_error,
                )
            else:
                # Ran out of links, save with current rate
                max_delay = PROBE_LEVELS[level][0]
                max_rate = 1.0 / max_delay
                self._save_approved_site(response.meta, max_crawl_rate=max_rate)

    def _collect_probe_links(self, response):
        """Gather internal links from a page, capped at 20."""
        root_parsed = urlparse(response.meta["root_url"])
        root_domain = root_parsed.netloc.lower()
        links = []
        seen = set()
        for href in response.css("a::attr(href)").getall():
            url = response.urljoin(href)
            parsed = urlparse(url)
            if parsed.netloc.lower() == root_domain and url not in seen:
                seen.add(url)
                links.append(url)
                if len(links) >= 20:
                    break
        return links

    def _save_approved_site(self, meta, max_crawl_rate):
        """INSERT into discovered_sites with ON CONFLICT DO UPDATE on root_url."""
        if not self._Session:
            logger.warning("No DB session available, cannot save site")
            return

        now = datetime.now(timezone.utc)
        session = self._Session()
        try:
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
            logger.info("Saved discovered site: %s (max_crawl_rate=%.2f req/s)", meta["root_url"], max_crawl_rate)
        except Exception as e:
            session.rollback()
            logger.error("Failed to save discovered site %s: %s", meta["root_url"], e)
        finally:
            session.close()

    def handle_error(self, failure):
        """Log request failures at debug level."""
        logger.debug("Request failed: %s", failure.value)

    def close_spider(self, reason):
        """Dispose DB engine on spider close."""
        if self._engine:
            self._engine.dispose()
