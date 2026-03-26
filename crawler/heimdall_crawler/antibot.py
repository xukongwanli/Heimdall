import re
import logging

logger = logging.getLogger(__name__)

ANTIBOT_PATTERNS = [
    r'captcha',
    r'recaptcha',
    r'hcaptcha',
    r'verify\s+(you\s+are|that\s+you\s+are)\s+human',
    r'are\s+you\s+a\s+robot',
    r'bot\s+detection',
    r'please\s+complete\s+the\s+challenge',
    r'cf-browser-verification',
    r'checking\s+your\s+browser',
    r'cloudflare\s+ray\s+id',
    r'akamai\s+bot\s+manager',
    r'akam/\d+',
    r'perimeterx',
    r'_px\d*\.js',
    r'blocked\s+by\s+px',
    r'datadome',
    r'js\.datadome\.co',
    r'access\s+denied.*automated',
    r'suspected\s+bot',
]

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in ANTIBOT_PATTERNS]


def detect_antibot(response):
    """Check if a Scrapy response contains antibot signals.
    Returns True if antibot measures are detected, False otherwise.
    """
    text = response.text
    if not text:
        return False

    for pattern in _compiled_patterns:
        if pattern.search(text):
            logger.info("Antibot detected on %s: matched pattern %s", response.url, pattern.pattern)
            return True

    return False
