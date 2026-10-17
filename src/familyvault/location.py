"""
FamilyVault Location Resolution
Reverse geocodes GPS coordinates into city/state/country names using the
offline `reverse_geocoder` dataset — no cloud API calls, no internet
required at runtime. Consistent with the project's no-cloud-dependency goal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from familyvault.logger import get_logger

log = get_logger(__name__)


# ── Data Class ─────────────────────────────────────────────────────────────────

@dataclass
class LocationResult:
    """Resolved place name for a single GPS coordinate."""
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    @property
    def has_location(self) -> bool:
        return self.city is not None or self.country is not None

    @property
    def display_name(self) -> str:
        """
        Human-readable "City, State, Country" string, gracefully
        degrading if any part is missing (e.g. a non-US location with
        no admin1 region resolves to "Paris, France" rather than
        leaving an empty slot).
        """
        parts = [p for p in (self.city, self.state, self.country) if p]
        return ", ".join(parts) if parts else "Unknown location"


# ── Country Display Names ──────────────────────────────────────────────────────

# reverse_geocoder only returns a 2-letter ISO country code (e.g. "US",
# "FR"), not a display name. This maps the codes most likely to show up
# in a home photo library to a readable name; anything not listed here
# falls back to the raw code (still usable, just less polished).
COUNTRY_DISPLAY_NAMES = {
    "US": "USA",
    "GB": "UK",
    "CA": "Canada",
    "MX": "Mexico",
    "FR": "France",
    "IT": "Italy",
    "ES": "Spain",
    "DE": "Germany",
    "JP": "Japan",
    "AU": "Australia",
    "NZ": "New Zealand",
    "IE": "Ireland",
    "NL": "Netherlands",
    "PT": "Portugal",
    "CH": "Switzerland",
    "AT": "Austria",
    "GR": "Greece",
    "TH": "Thailand",
    "CN": "China",
    "KR": "South Korea",
    "IN": "India",
    "BR": "Brazil",
    "ZA": "South Africa",
    "IS": "Iceland",
    "SE": "Sweden",
    "NO": "Norway",
    "DK": "Denmark",
}


def _display_country(cc: str) -> Optional[str]:
    """Map a 2-letter ISO country code to a display name, or None if empty."""
    if not cc:
        return None
    return COUNTRY_DISPLAY_NAMES.get(cc, cc)


# ── Resolution ─────────────────────────────────────────────────────────────────

def resolve_location(lat: float, lon: float) -> Optional[LocationResult]:
    """
    Resolve a single GPS coordinate to a city/state/country using the
    offline reverse_geocoder dataset (~33k populated places worldwide).

    This is nearest-populated-place matching, not a precise administrative
    boundary lookup — expect city-level accuracy. A rural coordinate
    resolves to the nearest town, not necessarily the exact township it
    falls within. No network access is made; the dataset ships with the
    package and is loaded into memory (as a k-d tree) on first use within
    a process, then reused for the rest of that process's lifetime.

    Args:
        lat: Latitude in decimal degrees.
        lon: Longitude in decimal degrees.

    Returns:
        LocationResult, or None if the lookup failed entirely (e.g.
        reverse_geocoder isn't installed, or an unexpected error occurred).
        A result with has_location == False means the library returned a
        match but it had no usable name/country data — treat the same as
        a failure for backfill purposes.
    """
    # (0.0, 0.0) — "null island" — is almost always a blank/default GPS
    # tag written by buggy camera or editing software, not a real photo
    # taken off the coast of West Africa. Treat it as "no location" rather
    # than resolving it to a misleading nearby place name.
    if lat == 0.0 and lon == 0.0:
        log.debug("Skipping (0.0, 0.0) — treated as missing GPS, not a real location")
        return LocationResult()

    try:
        import reverse_geocoder as rg
    except ImportError:
        log.error("reverse_geocoder is not installed — run: pip install reverse_geocoder")
        return None

    try:
        # mode=1 forces single-process lookup. reverse_geocoder's default
        # (mode=2) spins up a multiprocessing pool to parallelize across
        # the input list, which is wasteful overhead for a single-coordinate
        # call — we're already batching one-file-at-a-time in the CLI loop,
        # not relying on this call to parallelize.
        result = rg.search([(lat, lon)], mode=1)[0]
    except Exception as e:
        log.warning(f"Reverse geocode failed for ({lat}, {lon}): {e}")
        return None

    city = result.get("name") or None
    state = result.get("admin1") or None
    country = _display_country(result.get("cc", ""))

    return LocationResult(city=city, state=state, country=country)