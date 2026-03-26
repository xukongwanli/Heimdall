import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import scrapy
from scrapy.exceptions import CloseSpider
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from heimdall_crawler.antibot import detect_antibot
from heimdall_crawler.llm import suggest_sites

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

# (delay_seconds, num_requests) — starts slow, escalates
PROBE_LEVELS = [
    (10, 3),
    (5, 3),
    (2, 3),
    (1, 3),
]


class DiscoverySpider(scrapy.Spider):
    """Phase 1+2: Ask LLM for real estate websites, then probe for crawlability.

    Phase 1 asks DeepSeek to suggest real estate websites for the given regions.
    Phase 2 visits each suggested site and runs an escalating speed probe to
    test whether the site blocks crawlers.

    Usage:
        scrapy crawl discovery -a regions=TX,CA,FL
    """

    name = "discovery"

    def __init__(self, regions="TX", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.regions = [r.strip().upper() for r in regions.split(",") if r.strip()]
        self._known_domains = set()
        self._engine = None
        self._Session = None

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
            logger.info("Loaded %d known domains", len(self._known_domains))
        except Exception as e:
            logger.warning("Could not load discovered_sites: %s", e)
        finally:
            session.close()

        # Phase 1: Ask LLM for site suggestions
        region_names = [STATE_NAMES.get(r, r) for r in self.regions]
        base_url = self.settings.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
        model = self.settings.get("LLM_MODEL", "deepseek-chat")
        timeout = self.settings.getint("LLM_TIMEOUT", 30)

        logger.info("Asking LLM for real estate sites in: %s", ", ".join(region_names))
        urls = suggest_sites(region_names, api_key, base_url, model, timeout)

        if not urls:
            logger.warning("LLM returned no site suggestions")
            return

        logger.info("LLM suggested %d sites", len(urls))

        # Phase 2: Visit each suggested site and start probing
        for url in urls:
            parsed = urlparse(url)
            domain = parsed.netloc.lower().removeprefix("www.")

            if domain in self._known_domains:
                logger.info("Skipping known domain: %s", domain)
                continue

            self._known_domains.add(domain)
            yield scrapy.Request(
                url,
                callback=self.start_probe,
                meta={
                    "root_url": f"{parsed.scheme}://{parsed.netloc}",
                    "domain": domain,
                },
                errback=self.handle_error,
            )

    def start_probe(self, response):
        """Begin escalating probe on a candidate site."""
        if detect_antibot(response):
            logger.info("Antibot on initial visit to %s — skipping", response.url)
            return

        probe_links = self._collect_probe_links(response)
        if not probe_links:
            # Site has no internal links — save it anyway at slowest rate
            max_rate = 1.0 / PROBE_LEVELS[0][0]
            self._save_approved_site(response.meta, max_crawl_rate=max_rate)
            return

        yield scrapy.Request(
            probe_links[0],
            callback=self.probe_site,
            dont_filter=True,
            meta={
                "root_url": response.meta["root_url"],
                "domain": response.meta["domain"],
                "probe_level": 0,
                "probe_count": 0,
                "probe_links": probe_links[1:],
            },
            errback=self.handle_error,
        )

    def probe_site(self, response):
        """Escalating speed probe. Tests site at increasing request rates."""
        if detect_antibot(response):
            level = response.meta["probe_level"]
            if level == 0:
                logger.info(
                    "Antibot during probe of %s at level 0, abandoning",
                    response.meta["root_url"],
                )
                return
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
            next_level = level + 1
            if next_level >= len(PROBE_LEVELS):
                max_rate = 1.0 / PROBE_LEVELS[-1][0]
                logger.info(
                    "All probe levels passed for %s, saving with rate=%.2f req/s",
                    response.meta["root_url"], max_rate,
                )
                self._save_approved_site(response.meta, max_crawl_rate=max_rate)
                return

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
                        "probe_level": next_level,
                        "probe_count": 0,
                        "probe_links": probe_links[1:],
                        "download_delay": delay,
                    },
                    errback=self.handle_error,
                )
            else:
                max_rate = 1.0 / PROBE_LEVELS[level][0]
                self._save_approved_site(response.meta, max_crawl_rate=max_rate)
        else:
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
                        "probe_level": level,
                        "probe_count": count,
                        "probe_links": probe_links[1:],
                        "download_delay": delay,
                    },
                    errback=self.handle_error,
                )
            else:
                max_rate = 1.0 / PROBE_LEVELS[level][0]
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
                    "query": None,
                    "classification": None,
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
        logger.debug("Request failed: %s", failure.value)

    def close_spider(self, reason):
        if self._engine:
            self._engine.dispose()
