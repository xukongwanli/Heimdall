import json
import re

import scrapy
from heimdall_crawler.items import ListingItem


class RedfinSpider(scrapy.Spider):
    """Scrape Redfin search results.

    Redfin has an internal API (stingray) that returns JSON. We hit the search
    page with Playwright for initial rendering, then extract data from the
    embedded JSON or from their API endpoint.
    """

    name = "redfin"
    allowed_domains = ["redfin.com"]

    # Redfin uses its own state codes in URLs
    STATE_SLUGS = {
        "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
        "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
        "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho",
        "IL": "Illinois", "IN": "Indiana", "IA": "Iowa", "KS": "Kansas",
        "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine", "MD": "Maryland",
        "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota", "MS": "Mississippi",
        "MO": "Missouri", "MT": "Montana", "NE": "Nebraska", "NV": "Nevada",
        "NH": "New-Hampshire", "NJ": "New-Jersey", "NM": "New-Mexico", "NY": "New-York",
        "NC": "North-Carolina", "ND": "North-Dakota", "OH": "Ohio", "OK": "Oklahoma",
        "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode-Island", "SC": "South-Carolina",
        "SD": "South-Dakota", "TN": "Tennessee", "TX": "Texas", "UT": "Utah",
        "VT": "Vermont", "VA": "Virginia", "WA": "Washington", "WV": "West-Virginia",
        "WI": "Wisconsin", "WY": "Wyoming", "DC": "District-of-Columbia",
    }

    def __init__(self, region="TX", listing_type="buy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region = region.upper()
        self.listing_type = listing_type

    def start_requests(self):
        slug = self.STATE_SLUGS.get(self.region, self.region)
        if self.listing_type == "rent":
            url = f"https://www.redfin.com/state/{slug}/apartments-for-rent"
        else:
            url = f"https://www.redfin.com/state/{slug}"
        yield scrapy.Request(
            url,
            callback=self.parse,
            meta={"playwright": True, "playwright_include_page": False},
        )

    def parse(self, response):
        # Strategy 1: Look for embedded JSON data in script tags
        # Redfin embeds initial search results in a window.__reactServerState or
        # similar variable
        for script in response.css("script::text").getall():
            if "reactServerState" in script or "initialRedfinData" in script or "searchResultsData" in script:
                yield from self._parse_embedded_json(script, response)
                return

        # Strategy 2: Try to find the data in rdcHomes or homes array patterns
        for script in response.css("script::text").getall():
            if '"homes"' in script or '"homeData"' in script:
                yield from self._parse_homes_json(script, response)
                return

        # Strategy 3: Fall back to CSS selectors on the rendered DOM
        yield from self._parse_css(response)

    def _parse_embedded_json(self, script_text, response):
        # Extract JSON from variable assignment: window.__reactServerState = {...};
        match = re.search(r'=\s*(\{.+\})\s*;?\s*$', script_text, re.DOTALL)
        if not match:
            return

        try:
            data = json.loads(match.group(1))
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse embedded Redfin JSON")
            return

        homes = self._find_homes(data)
        if not homes:
            self.logger.warning("No homes found in embedded JSON")
            return

        for home in homes:
            item = self._extract_listing(home, response)
            if item:
                yield item

    def _parse_homes_json(self, script_text, response):
        # Try to extract a JSON array of homes
        match = re.search(r'"homes"\s*:\s*(\[.+?\])\s*[,}]', script_text, re.DOTALL)
        if not match:
            return

        try:
            homes = json.loads(match.group(1))
        except json.JSONDecodeError:
            return

        for home in homes:
            item = self._extract_listing(home, response)
            if item:
                yield item

    def _find_homes(self, data):
        """Recursively search for home listing arrays."""
        if isinstance(data, dict):
            for key in ["homes", "homeData", "searchResultsData", "listings"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val
                    if isinstance(val, dict):
                        for subkey in ["homes", "results", "listings"]:
                            if subkey in val and isinstance(val[subkey], list):
                                return val[subkey]
            for val in data.values():
                result = self._find_homes(val)
                if result:
                    return result
        return []

    def _extract_listing(self, home, response):
        """Extract a ListingItem from a Redfin JSON home object."""
        if not isinstance(home, dict):
            return None

        # Redfin nests data under homeData or directly
        home_data = home.get("homeData", home)

        # Address
        address_info = home_data.get("addressInfo", {}) or {}
        street = (
            address_info.get("formattedStreetLine", "")
            or home_data.get("streetAddress", "")
            or home_data.get("address", "")
        )
        if not street:
            return None

        item = ListingItem()
        item["source"] = "redfin"
        item["listing_type"] = self.listing_type
        item["address"] = street
        item["city"] = address_info.get("city", "") or home_data.get("city", "")
        item["region"] = address_info.get("state", "") or self.region
        item["postal_code"] = str(address_info.get("zip", "") or home_data.get("zip", ""))
        item["country"] = "US"

        # Price
        price_info = home_data.get("priceInfo", {}) or {}
        item["price"] = (
            price_info.get("amount")
            or home_data.get("price", {}).get("value")
            if isinstance(home_data.get("price"), dict)
            else home_data.get("price")
            or home_data.get("listingPrice")
        )

        # Sqft
        item["sqft"] = (
            home_data.get("sqFt", {}).get("value")
            if isinstance(home_data.get("sqFt"), dict)
            else home_data.get("sqFt")
            or home_data.get("sqft")
            or home_data.get("livingArea")
        )

        # URL
        url_path = home_data.get("url", "") or address_info.get("url", "")
        if url_path and not url_path.startswith("http"):
            url_path = f"https://www.redfin.com{url_path}"
        item["source_url"] = url_path or response.url

        item["published_at"] = None
        return item

    def _parse_css(self, response):
        """Fallback: parse rendered DOM with CSS selectors."""
        cards = response.css(".HomeCardContainer, .MapHomeCard")
        if not cards:
            self.logger.warning(
                f"No listing cards found on {response.url} — page structure may have changed"
            )
            return

        for card in cards:
            item = ListingItem()
            item["source"] = "redfin"
            item["listing_type"] = self.listing_type

            address = card.css(".homeAddressV2::text, .card-address::text, .link-and-anchor::text").get("")
            if not address:
                continue
            item["address"] = address
            item["city"] = ""
            item["region"] = self.region
            item["postal_code"] = ""
            item["country"] = "US"

            item["price"] = card.css(".homecardV2Price::text, .homecardV2Price span::text").get("")
            item["sqft"] = card.css(".HomeStatsV2 .stats span::text, .HomeCardContainer .sqft::text").re_first(r'([\d,]+)\s*[Ss]q')
            item["source_url"] = response.urljoin(card.css("a::attr(href)").get(""))
            item["published_at"] = None
            yield item
