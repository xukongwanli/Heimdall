BOT_NAME = "heimdall_crawler"
SPIDER_MODULES = ["heimdall_crawler.spiders"]
NEWSPIDER_MODULE = "heimdall_crawler.spiders"

# Anti-bot
ROBOTSTXT_OBEY = False
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 5
AUTOTHROTTLE_MAX_DELAY = 30
AUTOTHROTTLE_TARGET_CONCURRENCY = 1.0
DOWNLOAD_DELAY = 5
RANDOMIZE_DOWNLOAD_DELAY = True
CONCURRENT_REQUESTS = 1

# Retry on anti-bot responses (429 handled separately by BackoffRetryMiddleware)
RETRY_HTTP_CODES = [403, 500, 502, 503]
RETRY_TIMES = 5

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
    "heimdall_crawler.pipelines.EnrichmentPipeline": 150,
    "heimdall_crawler.pipelines.GeocodingPipeline": 200,
    "heimdall_crawler.pipelines.PostgresPipeline": 300,
    "heimdall_crawler.pipelines.MetricsRefreshPipeline": 400,
}

# Downloader middleware
DOWNLOADER_MIDDLEWARES = {
    "heimdall_crawler.middlewares.RotateUserAgentMiddleware": 400,
    "heimdall_crawler.middlewares.BackoffRetryMiddleware": 550,
    "scrapy.downloadermiddlewares.retry.RetryMiddleware": None,  # replaced by BackoffRetryMiddleware
}

# Database
DATABASE_URL = "postgresql://heimdall:heimdall@localhost:5433/heimdall"

# Logging
LOG_LEVEL = "INFO"

# Request settings
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
TWISTED_REACTOR = "twisted.internet.asyncioreactor.AsyncioSelectorReactor"
FEED_EXPORT_ENCODING = "utf-8"

# LLM — DeepSeek for page classification and selector generation
LLM_API_KEY = ""  # Set your DeepSeek API key here
LLM_BASE_URL = "https://api.deepseek.com/v1"
LLM_MODEL = "deepseek-chat"
LLM_TIMEOUT = 30  # seconds
