#!/usr/bin/env python
"""Run all spiders sequentially for both buy and rent listings."""
import subprocess
import sys


# Spiders that take region + listing_type args
LISTING_SPIDERS = ["realtor", "redfin"]
LISTING_TYPES = ["buy", "rent"]
REGIONS = ["TX"]  # Start with one state for testing

# Spiders that scrape aggregate data (no listing_type arg)
AGGREGATE_SPIDERS = ["numbeo"]


def main():
    regions = sys.argv[1:] if len(sys.argv) > 1 else REGIONS

    # Run aggregate spiders first (they produce both buy and rent data)
    for spider in AGGREGATE_SPIDERS:
        cmd = ["scrapy", "crawl", spider]
        print(f"\n{'='*60}")
        print(f"Running: {spider}")
        print(f"{'='*60}")
        result = subprocess.run(cmd, cwd=".")
        if result.returncode != 0:
            print(f"WARNING: {spider} exited with code {result.returncode}")

    # Run per-region listing spiders
    for region in regions:
        for spider in LISTING_SPIDERS:
            for listing_type in LISTING_TYPES:
                cmd = [
                    "scrapy", "crawl", spider,
                    "-a", f"region={region}",
                    "-a", f"listing_type={listing_type}",
                ]
                print(f"\n{'='*60}")
                print(f"Running: {spider} | {listing_type} | {region}")
                print(f"{'='*60}")
                result = subprocess.run(cmd, cwd=".")
                if result.returncode != 0:
                    print(f"WARNING: {spider} ({listing_type}, {region}) exited with code {result.returncode}")

    print(f"\n{'='*60}")
    print("All crawls complete.")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
