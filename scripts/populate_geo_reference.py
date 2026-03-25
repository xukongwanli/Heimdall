"""Download US Census Bureau gazetteer files and populate geo_reference table.

Usage:
    python scripts/populate_geo_reference.py

Downloads four TSV files from census.gov (~5 MB total), parses them, and
bulk-upserts rows into the geo_reference table. Idempotent — safe to re-run.
"""

import io
import re
import zipfile

import requests
from sqlalchemy import create_engine, text

DB_URL = "postgresql://heimdall:heimdall@localhost:5433/heimdall"

CENSUS_BASE = "https://www2.census.gov/geo/docs/maps-data/data/gazetteer"

GAZETTEER_URLS = {
    "state": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_state_national.zip",
    "county": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_counties_national.zip",
    "place": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_place_national.zip",
    "zcta": f"{CENSUS_BASE}/2024_Gazetteer/2024_Gaz_zcta_national.zip",
}

# State FIPS -> abbreviation mapping
STATE_FIPS_TO_ABBR = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA",
    "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL",
    "13": "GA", "15": "HI", "16": "ID", "17": "IL", "18": "IN",
    "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME",
    "24": "MD", "25": "MA", "26": "MI", "27": "MN", "28": "MS",
    "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI",
    "45": "SC", "46": "SD", "47": "TN", "48": "TX", "49": "UT",
    "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI",
    "56": "WY", "60": "AS", "66": "GU", "69": "MP", "72": "PR",
    "78": "VI",
}

SQMI_TO_SQFT = 27_878_400  # 1 square mile = 27,878,400 square feet


def download_and_extract(url: str) -> str:
    """Download a zip file and return the contents of the first .txt file inside."""
    print(f"  Downloading {url.split('/')[-1]}...")
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        txt_files = [n for n in zf.namelist() if n.endswith(".txt")]
        if not txt_files:
            raise ValueError(f"No .txt file found in {url}")
        return zf.read(txt_files[0]).decode("utf-8", errors="replace")


def parse_tsv(content: str) -> list[dict]:
    """Parse a tab-separated gazetteer file into a list of dicts."""
    lines = content.strip().split("\n")
    headers = [h.strip() for h in lines[0].split("\t")]
    rows = []
    for line in lines[1:]:
        fields = line.split("\t")
        row = {}
        for i, h in enumerate(headers):
            row[h] = fields[i].strip() if i < len(fields) else ""
        rows.append(row)
    return rows


def make_city_slug(city_name: str) -> str:
    """Convert city name to slug: lowercase, hyphens, no special chars."""
    slug = city_name.lower().strip()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"\s+", "-", slug)
    return slug


def safe_float(val: str) -> float | None:
    """Parse a string to float, returning None on failure."""
    try:
        return float(val.replace(",", "")) if val.strip() else None
    except ValueError:
        return None


def process_states(rows: list[dict]) -> list[dict]:
    """Process state gazetteer rows."""
    results = []
    for r in rows:
        usps = r.get("USPS", "").strip()
        geoid = r.get("GEOID", "").strip()
        if not usps:
            continue
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "state",
            "code": usps,
            "name": r.get("NAME", usps),
            "state_code": usps,
            "state_fips": geoid,
            "county_fips": None,
            "county_name": None,
            "city": None,
            "postal_code": None,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def process_counties(rows: list[dict]) -> list[dict]:
    """Process county gazetteer rows."""
    results = []
    for r in rows:
        geoid = r.get("GEOID", "").strip()
        if not geoid or len(geoid) < 4:
            continue
        state_fips = geoid[:2]
        state_code = STATE_FIPS_TO_ABBR.get(state_fips, "")
        if not state_code:
            continue
        name = r.get("NAME", "")
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "county",
            "code": geoid,
            "name": name,
            "state_code": state_code,
            "state_fips": state_fips,
            "county_fips": geoid,
            "county_name": name,
            "city": None,
            "postal_code": None,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def process_places(rows: list[dict]) -> list[dict]:
    """Process place (city) gazetteer rows."""
    results = []
    for r in rows:
        geoid = r.get("GEOID", "").strip()
        if not geoid or len(geoid) < 3:
            continue
        state_fips = geoid[:2]
        state_code = STATE_FIPS_TO_ABBR.get(state_fips, "")
        if not state_code:
            continue
        name = r.get("NAME", "").strip()
        # Remove suffixes like "city", "town", "CDP", "village" for matching
        city_clean = re.sub(r"\s+(city|town|CDP|village|borough|municipality)$", "", name, flags=re.IGNORECASE)
        slug = make_city_slug(city_clean)
        code = f"{slug}-{state_code.lower()}"
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "city",
            "code": code,
            "name": f"{city_clean}, {state_code}",
            "state_code": state_code,
            "state_fips": state_fips,
            "county_fips": None,
            "county_name": None,
            "city": city_clean.lower(),
            "postal_code": None,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def process_zctas(rows: list[dict]) -> list[dict]:
    """Process ZCTA (ZIP code) gazetteer rows."""
    results = []
    for r in rows:
        geoid = r.get("GEOID", "").strip()
        if not geoid or len(geoid) != 5:
            continue
        lat = safe_float(r.get("INTPTLAT", ""))
        lng = safe_float(r.get("INTPTLONG", ""))
        land = safe_float(r.get("ALAND_SQMI", ""))
        water = safe_float(r.get("AWATER_SQMI", ""))
        results.append({
            "level": "zip",
            "code": geoid,
            "name": geoid,
            "state_code": None,  # ZCTAs don't come with state — filled via spatial join later or enrichment
            "state_fips": None,
            "county_fips": None,
            "county_name": None,
            "city": None,
            "postal_code": geoid,
            "lat": lat,
            "lng": lng,
            "land_area_sqft": land * SQMI_TO_SQFT if land else None,
            "water_area_sqft": water * SQMI_TO_SQFT if water else None,
        })
    return results


def upsert_rows(engine, rows: list[dict]) -> int:
    """Bulk upsert rows into geo_reference. Returns count inserted/updated."""
    if not rows:
        return 0
    with engine.begin() as conn:
        for row in rows:
            geog_expr = f"ST_SetSRID(ST_MakePoint({row['lng']}, {row['lat']}), 4326)::geography" if row["lat"] and row["lng"] else "NULL"
            conn.execute(text(f"""
                INSERT INTO geo_reference (level, code, name, state_code, state_fips,
                    county_fips, county_name, city, postal_code, lat, lng, geog,
                    land_area_sqft, water_area_sqft)
                VALUES (:level, :code, :name, :state_code, :state_fips,
                    :county_fips, :county_name, :city, :postal_code, :lat, :lng,
                    {geog_expr},
                    :land_area_sqft, :water_area_sqft)
                ON CONFLICT (level, code) DO UPDATE SET
                    name = EXCLUDED.name,
                    state_code = EXCLUDED.state_code,
                    state_fips = EXCLUDED.state_fips,
                    county_fips = EXCLUDED.county_fips,
                    county_name = EXCLUDED.county_name,
                    city = EXCLUDED.city,
                    postal_code = EXCLUDED.postal_code,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    geog = EXCLUDED.geog,
                    land_area_sqft = EXCLUDED.land_area_sqft,
                    water_area_sqft = EXCLUDED.water_area_sqft
            """), row)
    return len(rows)


def main():
    engine = create_engine(DB_URL)
    total = 0

    print("Downloading and processing Census gazetteer files...")

    # States
    content = download_and_extract(GAZETTEER_URLS["state"])
    rows = process_states(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  States: {count} rows")
    total += count

    # Counties
    content = download_and_extract(GAZETTEER_URLS["county"])
    rows = process_counties(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  Counties: {count} rows")
    total += count

    # Places (cities)
    content = download_and_extract(GAZETTEER_URLS["place"])
    rows = process_places(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  Places: {count} rows")
    total += count

    # ZCTAs (ZIP codes)
    content = download_and_extract(GAZETTEER_URLS["zcta"])
    rows = process_zctas(parse_tsv(content))
    count = upsert_rows(engine, rows)
    print(f"  ZCTAs: {count} rows")
    total += count

    print(f"\nDone. Total rows upserted: {total}")
    engine.dispose()


if __name__ == "__main__":
    main()
