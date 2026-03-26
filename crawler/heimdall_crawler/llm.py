import json
import logging

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_MODEL = "deepseek-v3.2"
DEFAULT_TIMEOUT = 30


def _call_llm(messages, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """Make a chat completion request to the DeepSeek API. Returns the content string or None."""
    try:
        response = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={"model": model, "messages": messages},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.warning("LLM call failed: %s", e)
        return None


def classify_page(page_text, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """Ask DeepSeek whether a page contains real estate listing data.
    Returns dict like {"has_real_estate_data": True, "data_types": [...], "confidence": 0.9} or None on failure.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze web pages to determine if they contain real estate listing data. "
                "Respond ONLY with a JSON object: "
                '{"has_real_estate_data": bool, "data_types": [list of: "price", "address", "sqft", "bedrooms", "rent", "listing_type"], "confidence": float 0-1}'
            ),
        },
        {
            "role": "user",
            "content": f"Does this page contain real estate listing data?\n\n{page_text[:4000]}",
        },
    ]
    content = _call_llm(messages, api_key, base_url, model, timeout)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON: %s", content[:200])
        return None


def generate_selectors(page_html, api_key, base_url=DEFAULT_BASE_URL, model=DEFAULT_MODEL, timeout=DEFAULT_TIMEOUT):
    """Ask DeepSeek to generate CSS selectors for extracting listing fields.
    Returns dict like {"price": "span.price", "address": "h2.address"} or None on failure.
    """
    messages = [
        {
            "role": "system",
            "content": (
                "You analyze HTML to generate CSS selectors for extracting real estate listing data. "
                "Respond ONLY with a JSON object mapping field names to CSS selectors. "
                "Fields: price, address, sqft, bedrooms, listing_type, city, region, postal_code. "
                "Only include fields you can find selectors for. "
                'Example: {"price": "span.listing-price", "address": "h2.property-address"}'
            ),
        },
        {
            "role": "user",
            "content": f"Generate CSS selectors for real estate data in this HTML:\n\n{page_html[:6000]}",
        },
    ]
    content = _call_llm(messages, api_key, base_url, model, timeout)
    if content is None:
        return None
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        logger.warning("LLM returned non-JSON selectors: %s", content[:200])
        return None
