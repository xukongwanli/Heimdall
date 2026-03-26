import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.spiders.extraction import (
    extract_json_ld,
    extract_open_graph,
    extract_next_data,
)
import json
from scrapy.http import HtmlResponse


def _make_response(html):
    return HtmlResponse(url="https://example.com/listing/1", body=html.encode(), encoding="utf-8")


def test_extract_json_ld_real_estate():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "RealEstateListing", "name": "123 Main St", "price": "450000",
     "address": {"streetAddress": "123 Main St", "addressLocality": "Austin",
     "addressRegion": "TX", "postalCode": "78701"},
     "floorSize": {"value": "1800"}}
    </script>
    </head><body></body></html>
    """
    resp = _make_response(html)
    result = extract_json_ld(resp)
    assert result is not None
    assert result["address"] == "123 Main St"
    assert result["price"] == "450000"


def test_extract_json_ld_no_data():
    html = "<html><body><p>Hello world</p></body></html>"
    resp = _make_response(html)
    result = extract_json_ld(resp)
    assert result is None


def test_extract_next_data():
    data = {
        "props": {
            "pageProps": {
                "listings": [
                    {"price": 450000, "address": "123 Main St", "sqft": 1800}
                ]
            }
        }
    }
    html = f'<html><head></head><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></body></html>'
    resp = _make_response(html)
    result = extract_next_data(resp)
    assert result is not None
    assert len(result) >= 1


def test_extract_next_data_no_script():
    html = "<html><body><p>No next data</p></body></html>"
    resp = _make_response(html)
    result = extract_next_data(resp)
    assert result is None


def test_extract_open_graph():
    html = """
    <html><head>
    <meta property="og:type" content="real_estate.listing" />
    <meta property="og:title" content="456 Oak Ave, Dallas, TX" />
    <meta property="product:price:amount" content="350000" />
    </head><body></body></html>
    """
    resp = _make_response(html)
    result = extract_open_graph(resp)
    assert result is not None
    assert result["price"] == "350000"


def test_extract_open_graph_no_type():
    html = """
    <html><head>
    <meta property="og:type" content="website" />
    </head><body></body></html>
    """
    resp = _make_response(html)
    result = extract_open_graph(resp)
    assert result is None
