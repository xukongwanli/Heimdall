import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.spiders.discovery import DiscoverySpider, PROBE_LEVELS, SEARCH_TEMPLATES


def test_generates_search_queries():
    spider = DiscoverySpider(regions="TX,CA")
    queries = spider._build_search_queries()
    assert len(queries) > 0
    assert any("TX" in q or "Texas" in q for q in queries)
    assert any("CA" in q or "California" in q for q in queries)


def test_generates_queries_for_single_region():
    spider = DiscoverySpider(regions="TX")
    queries = spider._build_search_queries()
    assert all("TX" in q or "Texas" in q for q in queries)


def test_probe_levels_defined():
    assert len(PROBE_LEVELS) == 4
    delays = [level[0] for level in PROBE_LEVELS]
    assert delays == sorted(delays, reverse=True)


def test_search_templates_exist():
    assert len(SEARCH_TEMPLATES) >= 3
    for template in SEARCH_TEMPLATES:
        assert "{state_name}" in template
