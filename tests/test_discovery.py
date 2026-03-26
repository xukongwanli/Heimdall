import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'crawler'))

from heimdall_crawler.spiders.discovery import DiscoverySpider, PROBE_LEVELS, STATE_NAMES


def test_parses_regions():
    spider = DiscoverySpider(regions="TX,CA,FL")
    assert spider.regions == ["TX", "CA", "FL"]


def test_parses_single_region():
    spider = DiscoverySpider(regions="TX")
    assert spider.regions == ["TX"]


def test_probe_levels_defined():
    assert len(PROBE_LEVELS) == 4
    delays = [level[0] for level in PROBE_LEVELS]
    assert delays == sorted(delays, reverse=True)


def test_state_names_complete():
    assert len(STATE_NAMES) == 50
    assert STATE_NAMES["TX"] == "Texas"
    assert STATE_NAMES["CA"] == "California"
