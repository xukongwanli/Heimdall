import json

import scrapy
from heimdall_crawler.items import ListingItem


class RealtorSpider(scrapy.Spider):
    """Scrape Realtor.com search results.

    Realtor.com uses Next.js and embeds listing data in __NEXT_DATA__.
    It also provides JSON-LD structured data on some pages.
    """

    name = "realtor"
    allowed_domains = ["realtor.com"]

    def __init__(self, region="TX", listing_type="buy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region = region.upper()
        self.listing_type = listing_type

    def start_requests(self):
        state = self.region
        if self.listing_type == "rent":
            url = f"https://www.realtor.com/apartments/{state}"
        else:
            url = f"https://www.realtor.com/realestateandhomes-search/{state}"
        yield scrapy.Request(
            url,
            callback=self.parse,
            meta={"playwright": True, "playwright_include_page": False},
        )

    def parse(self, response):
        # Strategy 1: __NEXT_DATA__ (primary)
        next_data = response.css("script#__NEXT_DATA__::text").get()
        if next_data:
            yield from self._parse_next_data(next_data, response)
            return

        # Strategy 2: JSON-LD structured data
        for script in response.css('script[type="application/ld+json"]::text').getall():
            try:
                ld = json.loads(script)
                if isinstance(ld, list):
                    for item in ld:
                        if item.get("@type") in ("Product", "RealEstateListing", "Residence"):
                            yield from self._parse_jsonld(ld, response)
                            return
                elif ld.get("@type") in ("ItemList", "SearchResultsPage"):
                    yield from self._parse_jsonld_itemlist(ld, response)
                    return
            except json.JSONDecodeError:
                continue

        self.logger.warning(
            f"No listing data found on {response.url} — page structure may have changed"
        )

    def _parse_next_data(self, raw_json, response):
        try:
            data = json.loads(raw_json)
        except json.JSONDecodeError:
            self.logger.warning("Failed to parse __NEXT_DATA__ JSON")
            return

        # Realtor.com nests results under props.pageProps.properties or similar
        properties = self._find_properties(data)
        if not properties:
            self.logger.warning("No properties found in __NEXT_DATA__")
            return

        for prop in properties:
            item = self._extract_listing(prop, response)
            if item:
                yield item

    def _find_properties(self, data):
        """Recursively find the listings array in the JSON structure."""
        if isinstance(data, dict):
            # Known keys for Realtor.com
            for key in ["properties", "results", "listings", "home_search", "searchResults"]:
                if key in data:
                    val = data[key]
                    if isinstance(val, list):
                        return val
                    if isinstance(val, dict):
                        # Might have results nested one more level
                        for subkey in ["results", "properties", "listings"]:
                            if subkey in val and isinstance(val[subkey], list):
                                return val[subkey]
            # Recurse
            for val in data.values():
                result = self._find_properties(val)
                if result:
                    return result
        return []

    def _parse_jsonld(self, items, response):
        for item in items if isinstance(items, list) else [items]:
            if not isinstance(item, dict):
                continue
            address = item.get("address", {})
            if not address:
                continue
            listing = ListingItem()
            listing["source"] = "realtor"
            listing["listing_type"] = self.listing_type
            listing["address"] = address.get("streetAddress", "")
            listing["city"] = address.get("addressLocality", "")
            listing["region"] = address.get("addressRegion", "") or self.region
            listing["postal_code"] = address.get("postalCode", "")
            listing["country"] = "US"
            offers = item.get("offers", {})
            listing["price"] = offers.get("price") or item.get("price")
            listing["sqft"] = item.get("floorSize", {}).get("value") if isinstance(item.get("floorSize"), dict) else None
            listing["source_url"] = item.get("url", response.url)
            listing["published_at"] = None
            if listing["address"]:
                yield listing

    def _parse_jsonld_itemlist(self, data, response):
        elements = data.get("itemListElement", [])
        for el in elements:
            item = el.get("item", el)
            yield from self._parse_jsonld([item], response)

    def _extract_listing(self, prop, response):
        """Extract a ListingItem from a Realtor.com property JSON object."""
        if not isinstance(prop, dict):
            return None

        # Address can be in several formats
        location = prop.get("location", {}) or {}
        address_obj = location.get("address", {}) or prop.get("address", {}) or {}

        street = (
            address_obj.get("line", "")
            or address_obj.get("street_address", "")
            or address_obj.get("streetAddress", "")
            or prop.get("address", "") if isinstance(prop.get("address"), str) else ""
        )
        if not street:
            return None

        item = ListingItem()
        item["source"] = "realtor"
        item["listing_type"] = self.listing_type
        item["address"] = street
        item["city"] = (
            address_obj.get("city", "")
            or address_obj.get("addressLocality", "")
        )
        item["region"] = (
            address_obj.get("state_code", "")
            or address_obj.get("state", "")
            or address_obj.get("addressRegion", "")
            or self.region
        )
        item["postal_code"] = str(
            address_obj.get("postal_code", "")
            or address_obj.get("postalCode", "")
        )
        item["country"] = "US"

        # Price
        price = (
            prop.get("list_price")
            or prop.get("price")
            or prop.get("list_price_max")
        )
        if isinstance(price, dict):
            price = price.get("value") or price.get("max")
        item["price"] = price

        # Sqft
        description = prop.get("description", {}) or {}
        item["sqft"] = (
            description.get("sqft")
            or prop.get("sqft")
            or description.get("lot_sqft")
        )

        # URL
        permalink = prop.get("permalink", "") or prop.get("href", "")
        if permalink and not permalink.startswith("http"):
            permalink = f"https://www.realtor.com/realestateandhomes-detail/{permalink}"
        item["source_url"] = permalink or response.url

        item["published_at"] = None
        return item
