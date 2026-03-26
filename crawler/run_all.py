#!/usr/bin/env python
"""Run crawler in discover, extract, or combined mode.

Usage:
    python run_all.py discover [--regions TX CA FL]   # Phase 1+2: find new sites
    python run_all.py extract  [--regions TX CA FL]   # Phase 3: extract from approved sites
    python run_all.py all      [--regions TX CA FL]   # Both in sequence
"""
import argparse
import subprocess
import sys


DEFAULT_REGIONS = ["TX"]


def run_spider(spider, args=None):
    """Run a Scrapy spider as a subprocess. Returns True on success."""
    cmd = [sys.executable, "-m", "scrapy", "crawl", spider]
    if args:
        for key, value in args.items():
            cmd.extend(["-a", f"{key}={value}"])

    print(f"\n{'='*60}")
    print(f"Running: {spider} {args or ''}")
    print(f"{'='*60}")
    result = subprocess.run(cmd, cwd=".")
    if result.returncode != 0:
        print(f"WARNING: {spider} exited with code {result.returncode}")
        return False
    return True


def discover(regions):
    """Phase 1+2: Discover and probe new real estate websites."""
    run_spider("discovery", {"regions": ",".join(regions)})


def extract(regions):
    """Phase 3: Extract data from approved sites + Numbeo."""
    run_spider("numbeo")
    run_spider("extraction")


def main():
    parser = argparse.ArgumentParser(description="Heimdall crawler orchestration")
    parser.add_argument("mode", choices=["discover", "extract", "all"],
                        help="discover: find new sites, extract: scrape approved sites, all: both")
    parser.add_argument("--regions", nargs="+", default=DEFAULT_REGIONS,
                        help="US state abbreviations (default: TX)")
    args = parser.parse_args()

    if args.mode in ("discover", "all"):
        discover(args.regions)

    if args.mode in ("extract", "all"):
        extract(args.regions)

    print(f"\n{'='*60}")
    print(f"Crawl complete (mode: {args.mode}).")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
