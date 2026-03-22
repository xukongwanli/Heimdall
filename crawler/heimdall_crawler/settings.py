BOT_NAME = "heimdall_crawler"
SPIDER_MODULES = ["heimdall_crawler.spiders"]
NEWSPIDER_MODULE = "heimdall_crawler.spiders"

# Anti-bot
ROBOTSTXT_OBEY = False
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 2
AUTOTHROTTLE_MAX_DELAY = 10
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
DOWNLOAD_DELAY = 2
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS = 1

# Retry on anti-bot responses
RETRY_HTTP_CODES = [403, 429, 500, 502, 503]
RETRY_TIMES = 3

# Playwright — JS rendering for React-based listing sites
DOWNLOAD_HANDLERS = {
    "http": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
    "https": "scrapy_playwright.handler.ScrapyPlaywrightDownloadHandler",
}
PLAYWRIGHT_BROWSER_TYPE = "chromium"
PLAYWRIGHT_LAUNCH_OPTIONS = {"headless": True}

# Pipelines — order matters
ITEM_PIPELINES = {
    "heimdall_crawler.pipelines.CleaningPipeline": 100,
    "heimdall_crawler.pipelines.GeocodingPipeline": 200,
    "heimdall_crawler.pipelines.PostgresPipeline": 300,
    "heimdall_crawler.pipelines.MetricsRefreshPipeline": 400,
}

# Downloader middleware
DOWNLOADER_MIDDLEWARES = {
    "heimdall_crawler.middlewares.RotateUserAgentMiddleware": 400,
}

# Database
DATABASE_URL = "postgresql://heimdall:heimdall@localhost:5433/heimdall"

# Logging
LOG_LEVEL = "INFO"

# Request settings
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"
