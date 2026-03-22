import re

import scrapy
from heimdall_crawler.items import ListingItem


class NumbeoSpider(scrapy.Spider):
    """Scrape city-level property price data from Numbeo.

    Numbeo provides crowd-sourced aggregate data per city:
    - Buy price per sqft (city centre)
    - Rent per month (1BR/3BR, city centre)
    - Rental yield and price-to-rent ratios

    The country overview page has a table of all US cities. We follow each
    city link to get detailed price data, then store two synthetic listings
    per city (one buy, one rent) so the existing pipeline can compute metrics.
    """

    name = "numbeo"
    allowed_domains = ["numbeo.com"]

    def __init__(self, country="United+States", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.country = country

    def start_requests(self):
        url = f"https://www.numbeo.com/property-investment/country_result.jsp?country={self.country}"
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        """Parse the country overview table to get city links."""
        rows = response.css("table#t2 tbody tr")
        if not rows:
            self.logger.warning(
                f"No data table found on {response.url} — page structure may have changed"
            )
            return

        for row in rows:
            cells = row.css("td")
            if len(cells) < 2:
                continue

            city_link = cells[1].css("a")
            if not city_link:
                continue

            city_text = city_link.css("::text").get("").strip()
            href = city_link.attrib.get("href", "")

            # Parse "Austin, TX" -> city="Austin", region="TX"
            city_name, region = self._parse_city_state(city_text)
            if not city_name:
                continue

            # Extract index values from the table row
            meta = {
                "city_name": city_name,
                "region": region,
                "gross_rental_yield_centre": self._parse_float(cells[3].css("::text").get()),
                "price_to_rent_centre": self._parse_float(cells[5].css("::text").get()),
            }

            yield scrapy.Request(
                response.urljoin(href),
                callback=self.parse_city,
                meta=meta,
            )

    def parse_city(self, response):
        """Parse a city detail page for price per sqft and rent data."""
        city = response.meta["city_name"]
        region = response.meta["region"]

        text = response.text

        # Extract buy price per sqft (city centre)
        buy_price_sqft = self._extract_price_per_sqft(text, "buy")

        # Extract rent per month (1 bedroom, city centre)
        rent_1br = self._extract_rent(text)

        if buy_price_sqft:
            item = ListingItem()
            item["source"] = "numbeo"
            item["listing_type"] = "buy"
            item["address"] = f"{city} city centre average"
            item["city"] = city
            item["region"] = region
            item["postal_code"] = ""
            item["country"] = "US"
            item["price"] = buy_price_sqft  # price per sqft directly
            item["sqft"] = 1  # per-sqft price, so sqft=1 gives correct price_per_sqft
            item["source_url"] = response.url
            item["published_at"] = None
            yield item

        if rent_1br:
            # Convert monthly rent to a per-sqft basis
            # Average 1BR in US ~650 sqft
            avg_1br_sqft = 650
            item = ListingItem()
            item["source"] = "numbeo"
            item["listing_type"] = "rent"
            item["address"] = f"{city} city centre average"
            item["city"] = city
            item["region"] = region
            item["postal_code"] = ""
            item["country"] = "US"
            item["price"] = rent_1br
            item["sqft"] = avg_1br_sqft
            item["source_url"] = response.url
            item["published_at"] = None
            yield item

    def _extract_price_per_sqft(self, text, kind="buy"):
        """Extract 'Price per Square Feet to Buy Apartment in City Centre' value."""
        # Pattern: "Price per Square Feet to Buy Apartment in City Centre" followed by a number
        pattern = r'Price per Square Feet to Buy Apartment in City Centre[^0-9]*?([\d,]+\.?\d*)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return self._parse_float(match.group(1))

        # Also try "Square Meter" and convert (1 sqm = 10.764 sqft)
        pattern_m = r'Price per Square (?:Metre|Meter) to Buy Apartment in City Centre[^0-9]*?([\d,]+\.?\d*)'
        match_m = re.search(pattern_m, text, re.IGNORECASE)
        if match_m:
            price_sqm = self._parse_float(match_m.group(1))
            if price_sqm:
                return round(price_sqm / 10.764, 2)

        return None

    def _extract_rent(self, text):
        """Extract '1 Bedroom Apartment in City Centre' monthly rent."""
        pattern = r'Apartment \(1 bedroom\) in City Centre[^0-9]*?([\d,]+\.?\d*)'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return self._parse_float(match.group(1))

        # Alternative pattern
        pattern2 = r'1 [Bb]edroom Apartment in City Centre[^0-9]*?([\d,]+\.?\d*)'
        match2 = re.search(pattern2, text, re.IGNORECASE)
        if match2:
            return self._parse_float(match2.group(1))

        return None

    def _parse_city_state(self, text):
        """Parse 'Austin, TX' into ('austin', 'TX')."""
        match = re.match(r'^(.+?),\s*([A-Z]{2})$', text.strip())
        if match:
            return match.group(1).strip().lower(), match.group(2)
        return None, None

    def _parse_float(self, value):
        if not value:
            return None
        value = re.sub(r'[^\d.]', '', str(value))
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None
