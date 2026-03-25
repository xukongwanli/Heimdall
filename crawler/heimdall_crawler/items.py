import scrapy


class ListingItem(scrapy.Item):
    source = scrapy.Field()       # zillow, realtor, redfin
    listing_type = scrapy.Field() # buy, rent
    address = scrapy.Field()      # raw address string
    city = scrapy.Field()
    region = scrapy.Field()       # state abbreviation for US
    postal_code = scrapy.Field()
    country = scrapy.Field()
    price = scrapy.Field()        # numeric
    sqft = scrapy.Field()         # numeric or None
    source_url = scrapy.Field()
    published_at = scrapy.Field() # datetime or None (pipeline uses crawled_at as fallback)
    # Fields populated by pipelines (not by spiders)
    price_per_sqft = scrapy.Field()  # set by CleaningPipeline
    crawled_at = scrapy.Field()      # set by CleaningPipeline
    latitude = scrapy.Field()        # set by GeocodingPipeline
    longitude = scrapy.Field()       # set by GeocodingPipeline
    county_fips = scrapy.Field()     # set by EnrichmentPipeline
    county_name = scrapy.Field()     # set by EnrichmentPipeline
