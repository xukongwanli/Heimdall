import re
from datetime import datetime, timezone


ADDRESS_ABBREVIATIONS = {
    r'\bst\b': 'street',
    r'\bave\b': 'avenue',
    r'\bblvd\b': 'boulevard',
    r'\bdr\b': 'drive',
    r'\bln\b': 'lane',
    r'\brd\b': 'road',
    r'\bct\b': 'court',
    r'\bpl\b': 'place',
    r'\bapt\b': 'apartment',
    r'\bste\b': 'suite',
}


class CleaningPipeline:
    # Pattern: "123 Main St, Austin, TX 78701" or "123 Main St, Austin TX 78701"
    _address_tail_re = re.compile(
        r',\s*([a-zA-Z\s]+),?\s*([A-Z]{2})\s*(\d{5}(?:-\d{4})?)\s*$'
    )

    def process_item(self, item, spider):
        raw_address = item.get("address", "")
        # Try to extract city/state/zip from address tail if spider didn't provide them
        if not item.get("city") or not item.get("postal_code"):
            match = self._address_tail_re.search(raw_address)
            if match:
                if not item.get("city"):
                    item["city"] = match.group(1).strip()
                if not item.get("postal_code"):
                    item["postal_code"] = match.group(3)
                # Strip the city/state/zip tail from address
                raw_address = raw_address[:match.start()]

        item["address"] = self._normalize_address(raw_address)
        item["city"] = item.get("city", "").strip().lower()
        item["price"] = self._parse_number(item.get("price"), allow_zero=True)
        item["sqft"] = self._parse_number(item.get("sqft"), allow_zero=False)

        if item["sqft"] and item["sqft"] > 0 and item["price"]:
            item["price_per_sqft"] = round(item["price"] / item["sqft"], 2)
        else:
            item["price_per_sqft"] = None

        if not item.get("published_at"):
            item["published_at"] = datetime.now(timezone.utc)

        item["crawled_at"] = datetime.now(timezone.utc)
        return item

    def _normalize_address(self, address):
        address = address.strip().lower()
        # Normalize unit notation before abbreviation expansion to avoid double-expansion
        # e.g. "Apt #4" -> "apt 4" (the "apt" abbreviation will then expand to "apartment")
        address = re.sub(r'#\s*(\d+)', r'\1', address)
        # Expand abbreviations
        for pattern, replacement in ADDRESS_ABBREVIATIONS.items():
            address = re.sub(pattern, replacement, address)
        # Collapse whitespace
        address = re.sub(r'\s+', ' ', address)
        return address

    def _parse_number(self, value, allow_zero=False):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            result = float(value)
        else:
            value = re.sub(r'[^\d.]', '', str(value))
            if not value:
                return None
            result = float(value)
        if result < 0:
            return None
        if result == 0 and not allow_zero:
            return None
        return result


class GeocodingPipeline:
    def process_item(self, item, spider):
        return item


class PostgresPipeline:
    def process_item(self, item, spider):
        return item


class MetricsRefreshPipeline:
    def process_item(self, item, spider):
        return item
