import scrapy
from heimdall_crawler.items import ListingItem


class RealtorSpider(scrapy.Spider):
    name = "realtor"
    allowed_domains = ["realtor.com"]

    def __init__(self, region="TX", listing_type="buy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region = region
        self.listing_type = listing_type

    def start_requests(self):
        state = self.region
        if self.listing_type == "buy":
            url = f"https://www.realtor.com/realestateandhomes-search/{state}"
        else:
            url = f"https://www.realtor.com/apartments/{state}"
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        # NOTE: Selectors need tuning against live Realtor.com pages.
        cards = response.css("[data-testid='property-card']")
        if not cards:
            self.logger.warning(f"No listing cards found on {response.url} — page structure may have changed")

        for card in cards:
            item = ListingItem()
            item["source"] = "realtor"
            item["listing_type"] = self.listing_type
            full_address = card.css("[data-testid='card-address']::text").get("")
            item["address"] = full_address
            item["city"] = card.css("[data-testid='card-city']::text").get("")
            item["region"] = self.region
            item["postal_code"] = card.css("[data-testid='card-address']::text").re_first(r'(\d{5})') or ""
            item["country"] = "US"
            item["price"] = card.css("[data-testid='card-price']::text").get("")
            item["sqft"] = card.css("[data-testid='card-sqft']::text").re_first(r'([\d,]+)')
            item["source_url"] = response.urljoin(card.css("a::attr(href)").get(""))
            item["published_at"] = None
            yield item

        next_page = response.css("a[aria-label='Next']::attr(href)").get()
        if next_page:
            yield scrapy.Request(response.urljoin(next_page), callback=self.parse)
