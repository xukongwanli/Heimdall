import json
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.llm import classify_page, generate_selectors


FAKE_API_KEY = "test-key-123"


def _make_response(content: str, status_code: int = 200):
    """Build a mock httpx.Response-like object."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": content}}]
    }
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


class TestClassifyPage:
    def test_classify_page_returns_classification(self):
        """Successful response returns dict with expected keys."""
        payload = {
            "has_real_estate_data": True,
            "data_types": ["price", "address", "bedrooms"],
            "confidence": 0.95,
        }
        mock_resp = _make_response(json.dumps(payload))

        with patch("heimdall_crawler.llm.httpx.post", return_value=mock_resp) as mock_post:
            result = classify_page("some page text", api_key=FAKE_API_KEY)

        assert result is not None
        assert result["has_real_estate_data"] is True
        assert "data_types" in result
        assert "confidence" in result
        assert result["confidence"] == 0.95
        mock_post.assert_called_once()

    def test_classify_page_returns_none_on_timeout(self):
        """Exception during HTTP call returns None."""
        import httpx as _httpx

        with patch("heimdall_crawler.llm.httpx.post", side_effect=_httpx.TimeoutException("timed out")):
            result = classify_page("some page text", api_key=FAKE_API_KEY)

        assert result is None

    def test_classify_page_returns_none_on_bad_json(self):
        """Non-JSON response body returns None."""
        mock_resp = _make_response("This is not JSON at all.")

        with patch("heimdall_crawler.llm.httpx.post", return_value=mock_resp):
            result = classify_page("some page text", api_key=FAKE_API_KEY)

        assert result is None


class TestGenerateSelectors:
    def test_generate_selectors_returns_selectors(self):
        """Successful response returns dict with CSS selectors."""
        payload = {
            "price": "span.listing-price",
            "address": "h2.property-address",
            "bedrooms": "div.beds",
        }
        mock_resp = _make_response(json.dumps(payload))

        with patch("heimdall_crawler.llm.httpx.post", return_value=mock_resp) as mock_post:
            result = generate_selectors("<html>...</html>", api_key=FAKE_API_KEY)

        assert result is not None
        assert result["price"] == "span.listing-price"
        assert result["address"] == "h2.property-address"
        mock_post.assert_called_once()

    def test_generate_selectors_returns_none_on_failure(self):
        """Exception during HTTP call returns None."""
        import httpx as _httpx

        with patch("heimdall_crawler.llm.httpx.post", side_effect=Exception("network error")):
            result = generate_selectors("<html>...</html>", api_key=FAKE_API_KEY)

        assert result is None
