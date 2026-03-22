import scrapy
from heimdall_crawler.items import ListingItem


class RedfinSpider(scrapy.Spider):
    name = "redfin"
    allowed_domains = ["redfin.com"]

    def __init__(self, region="TX", listing_type="buy", *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.region = region
        self.listing_type = listing_type

    def start_requests(self):
        state = self.region
        if self.listing_type == "buy":
            url = f"https://www.redfin.com/state/{state}"
        else:
            url = f"https://www.redfin.com/state/{state}/apartments-for-rent"
        yield scrapy.Request(url, callback=self.parse)

    def parse(self, response):
        # NOTE: Selectors need tuning against live Redfin pages.
        cards = response.css(".HomeCardContainer")
        if not cards:
            self.logger.warning(f"No listing cards found on {response.url} — page structure may have changed")

        for card in cards:
            item = ListingItem()
            item["source"] = "redfin"
            item["listing_type"] = self.listing_type
            full_address = card.css(".homeAddressV2::text").get("")
            item["address"] = full_address
            item["city"] = card.css(".homeAddressV2 .city::text").get("")
            item["region"] = self.region
            item["postal_code"] = card.css(".homeAddressV2::text").re_first(r'(\d{5})') or ""
            item["country"] = "US"
            item["price"] = card.css(".homecardV2Price::text").get("")
            item["sqft"] = card.css(".HomeStatsV2 .stats span::text").re_first(r'([\d,]+)\s*[Ss]q')
            item["source_url"] = response.urljoin(card.css("a::attr(href)").get(""))
            item["published_at"] = None
            yield item

        next_page = response.css("button.nextButton a::attr(href)").get()
        if next_page:
            yield scrapy.Request(response.urljoin(next_page), callback=self.parse)
