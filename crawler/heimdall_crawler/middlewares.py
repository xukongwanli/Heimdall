import logging
import random
import time

from scrapy.downloadermiddlewares.retry import RetryMiddleware
from scrapy.utils.response import response_status_message

logger = logging.getLogger(__name__)


USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:134.0) Gecko/20100101 Firefox/134.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:134.0) Gecko/20100101 Firefox/134.0",
]


class RotateUserAgentMiddleware:
    def process_request(self, request, spider):
        request.headers["User-Agent"] = random.choice(USER_AGENTS)


class BackoffRetryMiddleware(RetryMiddleware):
    """Retry middleware that applies exponential backoff on 429 responses."""

    BACKOFF_DELAYS = [5, 15, 45, 120]  # seconds per retry attempt

    def process_response(self, request, response, spider):
        if response.status != 429:
            return response

        retries = request.meta.get("retry_times", 0)
        max_retries = self.max_retry_times

        if retries >= max_retries:
            logger.error(
                "Gave up on %s after %d retries (429 rate-limited)",
                request.url, retries,
            )
            return response

        # Respect Retry-After header if present, otherwise use backoff table
        retry_after = response.headers.get("Retry-After")
        if retry_after:
            delay = int(retry_after)
        else:
            delay = self.BACKOFF_DELAYS[min(retries, len(self.BACKOFF_DELAYS) - 1)]

        logger.info(
            "429 on %s — waiting %ds before retry %d/%d",
            request.url, delay, retries + 1, max_retries,
        )
        time.sleep(delay)

        reason = response_status_message(response.status)
        return self._retry(request, reason, spider) or response
