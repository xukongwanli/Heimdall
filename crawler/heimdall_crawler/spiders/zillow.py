import scrapy
from heimdall_crawler.items import ListingItem


class ZillowSpider(scrapy.Spider):
    name = "zillow"
    allowed_domains = ["zillow.com"]

    def __init__(self, region="TX", listing_type="buy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region = region
        self.listing_type = listing_type

    def start_requests(self):
        if self.listing_type == "buy":
            url = f"https://www.zillow.com/homes/for_sale/{self.region}/"
        else:
            url = f"https://www.zillow.com/homes/for_rent/{self.region}/"
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        # NOTE: Selectors need tuning against live Zillow pages.
        # Zillow uses heavy JS rendering — may need Playwright middleware for production use.
        cards = response.css("article[data-test='property-card']")
        if not cards:
            self.logger.warning(f"No listing cards found on {response.url} — page structure may have changed")

        for card in cards:
            item = ListingItem()
            item["source"] = "zillow"
            item["listing_type"] = self.listing_type
            # Address often includes "City, ST ZIP" — CleaningPipeline will parse
            full_address = card.css("[data-test='property-card-addr']::text").get("")
            item["address"] = full_address
            item["city"] = card.css("[data-test='property-card-addr'] span::text").get("")
            item["region"] = self.region
            item["postal_code"] = card.css("[data-test='property-card-addr']::text").re_first(r'(\d{5})') or ""
            item["country"] = "US"
            item["price"] = card.css("[data-test='property-card-price']::text").get("")
            item["sqft"] = card.css(".property-card-link span::text").re_first(r'([\d,]+)\s*sq')
            item["source_url"] = response.urljoin(card.css("a::attr(href)").get(""))
            item["published_at"] = None
            yield item

        # Follow pagination
        next_page = response.css("a[rel='next']::attr(href)").get()
        if next_page:
            yield scrapy.Request(response.urljoin(next_page), callback=self.parse)
