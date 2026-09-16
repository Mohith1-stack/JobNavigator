"""The country vocabulary for Indeed searches, read from the jobspy library.

jobspy picks the Indeed domain and the `indeed-co` API header from the
`country_indeed` string it receives, and it accepts only the names its own
`Country` enum knows. The project therefore keeps no country list of its own:
every name here comes from `jobspy.model.Country` at call time, so a library
upgrade adds or removes countries without a code change.
"""

from functools import lru_cache
from typing import Optional

# The value a search falls back to when nothing says where to look. It is a
# jobspy alias, so `Country.from_string()` always accepts it.
DEFAULT_COUNTRY = "usa"

# Two enum members are routing values for other boards, not places a user picks:
# US_CANADA belongs to ZipRecruiter and WORLDWIDE to LinkedIn. Neither selects an
# Indeed domain, so both stay out of the list and out of validation.
_INTERNAL_MEMBERS = frozenset({"US_CANADA", "WORLDWIDE"})


def _aliases(member) -> list:
    """The spellings `Country.from_string()` accepts for one enum member."""
    return [a.strip() for a in member.value[0].split(",") if a.strip()]


@lru_cache(maxsize=1)
def supported_countries() -> tuple:
    """((value, label), ...) for every country Indeed supports, sorted by label.

    `value` is the first alias, which is what the project stores and hands back
    to jobspy. `label` is the longest alias, which reads as the full name of the
    country ("usa" -> "United States", "uk" -> "United Kingdom").
    """
    from jobspy.model import Country

    rows = [
        (_aliases(member)[0], max(_aliases(member), key=len).title())
        for member in Country
        if member.name not in _INTERNAL_MEMBERS
    ]
    return tuple(sorted(rows, key=lambda row: row[1]))


def normalize_country(value) -> Optional[str]:
    """The stored form of a country name, or None when jobspy does not know it.

    The match is case-insensitive and accepts every alias jobspy accepts, so
    "Canada", "canada", "US" and "United States" all resolve.
    """
    from jobspy.model import Country

    try:
        member = Country.from_string(str(value or ""))
    except (ValueError, AttributeError):
        return None
    if member.name in _INTERNAL_MEMBERS:
        return None
    return _aliases(member)[0]


def country_from_location(location) -> str:
    """Read a country out of free location text.

    The last comma-separated segment comes first ("Toronto, Canada" -> canada),
    then the whole trimmed string ("Canada" -> canada). Text that matches
    neither gives DEFAULT_COUNTRY. This is a one-time guess for the migration
    backfill, not a runtime substitute for the stored field.
    """
    text = str(location or "").strip()
    for candidate in (text.rsplit(",", 1)[-1], text):
        name = normalize_country(candidate.strip())
        if name:
            return name
    return DEFAULT_COUNTRY
