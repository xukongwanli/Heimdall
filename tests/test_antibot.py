import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from unittest.mock import MagicMock
from heimdall_crawler.antibot import detect_antibot


def _make_response(body_text, url="https://example.com"):
    resp = MagicMock()
    resp.text = body_text
    resp.url = url
    resp.status = 200
    return resp


def test_detects_captcha_keyword():
    resp = _make_response("Please complete the CAPTCHA to continue")
    assert detect_antibot(resp) is True


def test_detects_cloudflare_challenge():
    resp = _make_response('<div class="cf-browser-verification">Checking your browser</div>')
    assert detect_antibot(resp) is True


def test_detects_verify_human():
    resp = _make_response("We need to verify you are human before proceeding")
    assert detect_antibot(resp) is True


def test_detects_perimeterx():
    resp = _make_response("blocked by PerimeterX")
    assert detect_antibot(resp) is True


def test_detects_datadome():
    resp = _make_response('<script src="https://js.datadome.co/tags.js"></script>')
    assert detect_antibot(resp) is True


def test_normal_page_passes():
    resp = _make_response("<html><body><h1>Homes for sale</h1><p>$450,000</p></body></html>")
    assert detect_antibot(resp) is False


def test_empty_page_passes():
    resp = _make_response("")
    assert detect_antibot(resp) is False
