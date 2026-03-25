#!/usr/bin/env bash
# Downloads US Census TIGER cartographic boundary files and converts to GeoJSON.
# Uses 20m resolution (most simplified) for smaller file sizes.
# Requires: curl, python3 (with json module)
#
# IMPORTANT: The state GeoJSON must have a STUSPS property (2-letter state abbrev)
# and the county GeoJSON must have a GEOID property (5-digit FIPS code).
# These properties are used by ChoroplethMap.vue to match aggregated data to polygons.

set -euo pipefail

GEO_DIR="$(dirname "$0")/../public/geo"
mkdir -p "$GEO_DIR"
GEO_DIR="$(cd "$GEO_DIR" && pwd)"

echo "Downloading US states (20m shapefile)..."
TMPDIR=$(mktemp -d)
curl -sL "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_20m.zip" \
  -o "$TMPDIR/states.zip"

echo "Downloading US counties (20m shapefile)..."
curl -sL "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_20m.zip" \
  -o "$TMPDIR/counties.zip"

# Check if ogr2ogr is available for shapefile→GeoJSON conversion
if command -v ogr2ogr &> /dev/null; then
  echo "Converting shapefiles to GeoJSON with ogr2ogr..."
  cd "$TMPDIR"
  unzip -qo states.zip
  unzip -qo counties.zip
  ogr2ogr -f GeoJSON "$GEO_DIR/us-states.json" cb_2024_us_state_20m.shp
  ogr2ogr -f GeoJSON "$GEO_DIR/us-counties.json" cb_2024_us_county_20m.shp
else
  echo "ogr2ogr not found. Install GDAL for shapefile conversion:"
  echo "  brew install gdal    # macOS"
  echo "  apt install gdal-bin # Debian/Ubuntu"
  echo ""
  echo "Falling back to pre-converted GeoJSON from GitHub..."
  echo "NOTE: These may lack STUSPS/GEOID properties. Verify after download."

  # Fallback: use Eric Celeste's pre-converted Census GeoJSON (preserves TIGER properties)
  curl -sL "https://eric.clst.org/assets/wiki/uploads/Stuff/gz_2010_us_040_00_20m.json" \
    -o "$GEO_DIR/us-states.json"
  curl -sL "https://raw.githubusercontent.com/plotly/datasets/master/geojson-counties-fips.json" \
    -o "$GEO_DIR/us-counties.json"

  # The Eric Celeste states file uses NAME (full name) and STATE (FIPS number).
  # We need to add STUSPS. Use python to add state abbreviations.
  GEO_DIR="$GEO_DIR" python3 << 'PYEOF'
import json

STATE_FIPS_TO_ABBREV = {
    "01":"AL","02":"AK","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT",
    "10":"DE","11":"DC","12":"FL","13":"GA","15":"HI","16":"ID","17":"IL",
    "18":"IN","19":"IA","20":"KS","21":"KY","22":"LA","23":"ME","24":"MD",
    "25":"MA","26":"MI","27":"MN","28":"MS","29":"MO","30":"MT","31":"NE",
    "32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC","38":"ND",
    "39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
    "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV",
    "55":"WI","56":"WY","60":"AS","66":"GU","69":"MP","72":"PR","78":"VI",
}

import os
geo_dir = os.environ.get("GEO_DIR", ".")
path = os.path.join(geo_dir, "us-states.json")
with open(path) as f:
    data = json.load(f)

for feature in data.get("features", []):
    props = feature.get("properties", {})
    fips = props.get("STATE", "")
    if fips in STATE_FIPS_TO_ABBREV:
        props["STUSPS"] = STATE_FIPS_TO_ABBREV[fips]

with open(path, "w") as f:
    json.dump(data, f, separators=(",", ":"))

print(f"Added STUSPS to {len(data.get('features', []))} state features")
PYEOF
fi

rm -rf "$TMPDIR"

echo "Done. Files saved to $GEO_DIR/"
echo "  us-states.json: $(wc -c < "$GEO_DIR/us-states.json") bytes"
echo "  us-counties.json: $(wc -c < "$GEO_DIR/us-counties.json") bytes"

# Verify required properties exist
python3 -c "
import json
states = json.load(open('$GEO_DIR/us-states.json'))
f = states['features'][0]['properties']
assert 'STUSPS' in f or 'STUSPS' in str(f), 'ERROR: us-states.json missing STUSPS property!'
print(f'States: {len(states[\"features\"])} features, properties: {list(f.keys())}')

counties = json.load(open('$GEO_DIR/us-counties.json'))
f2 = counties['features'][0]['properties']
print(f'Counties: {len(counties[\"features\"])} features, properties: {list(f2.keys())}')
"
