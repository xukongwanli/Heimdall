# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Heimdall is a global real estate data aggregation platform. It crawls publicly available, free information about buying and renting homes worldwide, stores it, and serves it through a web interface. Data refreshes approximately every hour.

## Architecture (Planned)

- **Crawler layer**: Python-based web scrapers that collect real estate listings from public sources globally. Must be capable of bypassing CAPTCHA and bot detection. Only freely available, public data is in scope—sources requiring user login or paid access are excluded.
- **Data storage**: Collected listing data persisted for serving and historical tracking. Total storage budget is 200 GB max.
- **Web frontend**: Displays aggregated listings with ~1-hour update cadence

## Development Status

This project is in early development. The architecture and tooling described here are preliminary and subject to change as the project evolves.
