import json

import scrapy
from heimdall_crawler.items import ListingItem


class ZillowSpider(scrapy.Spider):
    """Scrape Zillow search results by extracting JSON data embedded in the page.

    Zillow renders via React and embeds listing data in a <script id="__NEXT_DATA__">
    tag. This is more reliable than CSS selectors against their JS-rendered DOM.
    """

    name = "zillow"
    allowed_domains = ["zillow.com"]

    # Zillow state URL sluges (lowercase full name)
    STATE_SLUGS = {
        "AL": "alabama", "AK": "alaska", "AZ": "arizona", "AR": "arkansas",
        "CA": "california", "CO": "colorado", "CT": "connecticut", "DE": "delaware",
        "FL": "florida", "GA": "georgia", "HI": "hawaii", "ID": "idaho",
        "IL": "illinois", "IN": "indiana", "IA": "iowa", "KS": "kansas",
        "KY": "kentucky", "LA": "louisiana", "ME": "maine", "MD": "maryland",
        "MA": "massachusetts", "MI": "michigan", "MN": "minnesota", "MS": "mississippi",
        "MO": "missouri", "MT": "montana", "NE": "nebraska", "NV": "nevada",
        "NH": "new-hampshire", "NJ": "new-jersey", "NM": "new-mexico", "NY": "new-york",
        "NC": "north-carolina", "ND": "north-dakota", "OH": "ohio", "OK": "oklahoma",
        "OR": "oregon", "PA": "pennsylvania", "RI": "rhode-island", "SC": "south-carolina",
        "SD": "south-dakota", "TN": "tennessee", "TX": "texas", "UT": "utah",
        "VT": "vermont", "VA": "virginia", "WA": "washington", "WV": "west-virginia",
        "WI": "wisconsin", "WY": "wyoming", "DC": "washington-dc",
    }

    def __init__(self, region="TX", listing_type="buy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region = region.upper()
        self.listing_type = listing_type

    def start_requests(self):
        slug = self.STATE_SLUGS.get(self.region, self.region.lower())
        if self.listing_type == "rent":
            url = f"https://www.zillow.com/homes/for_rent/{slug}/"
        else:
            url = f"https://www.zillow.com/homes/for_sale/{slug}/"
        yield scrapy.Request(
            url,
            callback=self.parse,
            meta={"playwright": True, "playwright_include_page": False},
        )

    def parse(self, response):
        # Strategy 1: Extract from __NEXT_DATA__ JSON
        next_data = response.css("script#__NEXT_DATA__::text").get()
        if next_data:
            yield from self._parse_next_data(next_data, response)
            return

        # Strategy 2: Extract from inline JSON in script tags
        # Zillow sometimes embeds search results in a different script pattern
        for script in response.css("script::text").getall():
            if '"listResults"' in script or '"searchResults"' in script:
                yield from self._parse_inline_json(script, response)
                return

        self.logger.warning(
            f"No listing data found on {response.url} — page structure may have changed"
        )

    def _parse_next_data(self, raw_json, response):
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse __NEXT_DATA__ JSON")
            return

        # Navigate the nested structure to find search results
        results = self._find_search_results(data)
        if not results:
            self.logger.warning("No search results found in __NEXT_DATA__")
            return

        for result in results:
            item = self._extract_listing(result, response)
            if item:
                yield item

    def _parse_inline_json(self, script_text, response):
        # Try to find JSON object containing listing data
        for marker in ['"listResults"', '"searchResults"']:
            idx = script_text.find(marker)
            if idx == -1:
                continue
            # Walk back to find the opening brace
            brace_depth = 0
            start = idx
            for i in range(idx, -1, -1):
                if script_text[i] == "}":
                    brace_depth += 1
                elif script_text[i] == "{":
                    if brace_depth == 0:
                        start = i
                        break
                    brace_depth -= 1
            # Walk forward to find balanced closing brace
            brace_depth = 0
            end = len(script_text)
            for i in range(start, len(script_text)):
                if script_text[i] == "{":
                    brace_depth += 1
                elif script_text[i] == "}":
                    brace_depth -= 1
                    if brace_depth == 0:
                        end = i + 1
                        break
            try:
                data = json.loads(script_text[start:end])
                results = self._find_search_results(data)
                for result in results:
                    item = self._extract_listing(result, response)
                    if item:
                        yield item
            except json.JSONDecodeError:
                continue

    def _find_search_results(self, data):
        """Recursively search for listing arrays in nested JSON."""
        if isinstance(data, dict):
            # Known keys where Zillow puts listings
            for key in ["listResults", "searchResults", "mapResults"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val
                    if isinstance(val, dict) and "listResults" in val:
                        return val["listResults"]
            # Recurse into nested dicts
            for val in data.values():
                result = self._find_search_results(val)
                if result:
                    return result
        return []

    def _extract_listing(self, result, response):
        """Extract a ListingItem from a Zillow JSON result object."""
        if not isinstance(result, dict):
            return None

        address_str = (
            result.get("address", "")
            or result.get("streetAddress", "")
            or result.get("addressStreet", "")
        )
        if not address_str:
            return None

        item = ListingItem()
        item["source"] = "zillow"
        item["listing_type"] = self.listing_type
        item["address"] = address_str
        item["city"] = result.get("addressCity", "") or result.get("city", "")
        item["region"] = result.get("addressState", "") or self.region
        item["postal_code"] = str(result.get("addressZipcode", "") or result.get("zipcode", ""))
        item["country"] = "US"

        price = result.get("price") or result.get("unformattedPrice") or result.get("priceForHDP")
        if isinstance(price, str):
            price = price.replace("$", "").replace(",", "").replace("+", "").replace("/mo", "")
        item["price"] = price

        sqft = result.get("area") or result.get("livingArea") or result.get("hdpData", {}).get("homeInfo", {}).get("livingArea")
        item["sqft"] = sqft

        detail_url = result.get("detailUrl") or result.get("url") or ""
        if detail_url and not detail_url.startswith("http"):
            detail_url = response.urljoin(detail_url)
        item["source_url"] = detail_url or response.url

        item["published_at"] = None
        return item
