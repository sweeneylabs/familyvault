"""
FamilyVault Query Parser
Parses a single free-text search string into structured pieces — year,
month, season, person names — plus whatever text is left over, so one
search field can answer queries like "birthday Paris summer 2019" or
"Patrick skiing" as a single combined filter rather than requiring
separate fields.

This module only parses text; it has no database dependency and knows
nothing about GPS, hemisphere, or which people actually exist in the
database. Season is returned as a plain name (e.g. "summer") and
resolved into actual calendar months per file by the database layer,
which knows each file's hemisphere from its GPS coordinates — see
_build_date_clause() in database.py. Likewise, person names are
returned as plain strings; resolving a name to a person id (and
building the AND/NOT-EXISTS SQL against the faces table) happens in
database.py's _build_person_clause(), since that's where the current
roster of named people actually lives.

Because person names come from a dynamic, growing roster rather than a
fixed vocabulary (unlike month/season names), parse_query() takes the
current list of known names as a parameter rather than hardcoding
them — the caller (the /search endpoint) is responsible for fetching
that list from the database before parsing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class ParsedQuery:
    """The pieces extracted from a raw search string."""
    text: str
    year: Optional[int] = None
    month: Optional[int] = None       # 1-12
    season: Optional[str] = None      # "winter" | "spring" | "summer" | "fall"
    person_names: list[str] = field(default_factory=list)           # must ALL appear in the file (AND)
    excluded_person_names: list[str] = field(default_factory=list)  # must NONE appear in the file

    @property
    def has_date_filter(self) -> bool:
        return self.year is not None or self.month is not None or self.season is not None

    @property
    def has_text(self) -> bool:
        return bool(self.text.strip())

    @property
    def has_person_filter(self) -> bool:
        return bool(self.person_names) or bool(self.excluded_person_names)

    @property
    def is_empty(self) -> bool:
        """
        True if nothing was parsed at all — no date filter, no person
        filter, and no leftover text. parse_query("") produces this,
        and so does any query that turns out to be entirely date words
        and/or person names with nothing else. search_media() in
        database.py treats this as "return everything" — this is what
        powers the default gallery view shown before anyone has typed
        a search.
        """
        return not self.has_date_filter and not self.has_text and not self.has_person_filter


# ── Vocabulary ─────────────────────────────────────────────────────────────────

_MONTH_NAMES = {
    "january": 1, "jan": 1,
    "february": 2, "feb": 2,
    "march": 3, "mar": 3,
    "april": 4, "apr": 4,
    "may": 5,
    "june": 6, "jun": 6,
    "july": 7, "jul": 7,
    "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9,
    "october": 10, "oct": 10,
    "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}

# "autumn" and "fall" both resolve to the same canonical season name.
_SEASON_NAMES = {
    "winter": "winter",
    "spring": "spring",
    "summer": "summer",
    "fall": "fall",
    "autumn": "fall",
}

_YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")

# Sorted longest-first for readability; not load-bearing for correctness
# since \b word-boundary matching already prevents partial-word overlap
# regardless of alternation order (e.g. "sep" can't accidentally eat
# part of "september" either way).
_MONTH_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_MONTH_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)
_SEASON_PATTERN = re.compile(
    r"\b(" + "|".join(sorted(_SEASON_NAMES, key=len, reverse=True)) + r")\b",
    re.IGNORECASE,
)

# Filler words stripped out after a person name is recognized, so
# "Patrick and Tamika" doesn't leave a stray "and" behind to be
# (wrongly) matched against captions as free text. Only applied when at
# least one person name was actually found — a query with no person
# names leaves "and"/"with" untouched, since those could be meaningful
# in an ordinary caption search (e.g. "fish and chips").
_PERSON_FILLER_PATTERN = re.compile(r"\b(and|with)\b", re.IGNORECASE)


# ── Parsing ────────────────────────────────────────────────────────────────────

def parse_query(raw: str, known_person_names: Optional[list[str]] = None) -> ParsedQuery:
    """
    Parse a free-text search string into year/month/season/person
    names plus leftover free text (matched against captions and
    location fields downstream).

    Only the first match of each date kind is used — a query
    containing two years, for instance, keeps only the first. If both
    an explicit month and a season word appear, both are stripped out
    of the leftover text (so neither pollutes the free-text match),
    but only the month is kept as the *active* date filter — it's more
    precise. See _build_date_clause() in database.py for where that
    priority is actually applied.

    Person names are matched case-insensitively as whole words against
    known_person_names, longest name first (so a multi-word name like
    "Mary Jane" is matched whole before a shorter name that happens to
    be a prefix of it). "NOT <name>" (case-insensitive) is checked
    first and adds to excluded_person_names instead of person_names;
    an excluded name is never also treated as an include even if it
    appears elsewhere in the query unmatched by "not". Every included
    name in a query is required (AND, not OR) — "Patrick and Tamika"
    means both people must appear in the same file, matching how a
    person would naturally read that phrase.

    Known limitation: short month abbreviations that double as common
    English words — "may" being the obvious one — will be read as a
    date token even when meant literally (e.g. as part of someone's
    name). Month/season extraction runs before person-name extraction,
    so a person named "May" would currently be misread as the month
    every time. Treated as an acceptable tradeoff for now, same as the
    pre-existing "may I see this" limitation noted below — worth
    revisiting if it turns out to bite in practice.

    Args:
        raw: The raw search string as typed by the user.
        known_person_names: The current roster of named people (e.g.
            from database.get_named_people()), used to recognize names
            in the query text. None or empty disables person-name
            matching entirely — every word is left as free text.

    Returns:
        A ParsedQuery with whatever date/person pieces were found, and
        the remaining text (may be empty).
    """
    text = raw or ""

    year: Optional[int] = None
    year_match = _YEAR_PATTERN.search(text)
    if year_match:
        year = int(year_match.group(0))
        text = text[:year_match.start()] + text[year_match.end():]

    month: Optional[int] = None
    month_match = _MONTH_PATTERN.search(text)
    if month_match:
        month = _MONTH_NAMES[month_match.group(1).lower()]
        text = text[:month_match.start()] + text[month_match.end():]

    season: Optional[str] = None
    season_match = _SEASON_PATTERN.search(text)
    if season_match:
        season = _SEASON_NAMES[season_match.group(1).lower()]
        text = text[:season_match.start()] + text[season_match.end():]

    person_names: list[str] = []
    excluded_person_names: list[str] = []

    if known_person_names:
        # Longest names first so a multi-word name matches whole
        # before a shorter name that happens to be a substring/prefix
        # of it.
        sorted_names = sorted(set(known_person_names), key=len, reverse=True)

        # Exclusions ("not Owen") are checked before plain inclusions,
        # so a name mentioned only in a "not" clause is never also
        # picked up as an include.
        for name in sorted_names:
            pattern = re.compile(r"\bnot\s+" + re.escape(name) + r"\b", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                excluded_person_names.append(name)
                text = text[:match.start()] + text[match.end():]

        for name in sorted_names:
            if name in excluded_person_names:
                continue
            pattern = re.compile(r"\b" + re.escape(name) + r"\b", re.IGNORECASE)
            match = pattern.search(text)
            if match:
                person_names.append(name)
                text = text[:match.start()] + text[match.end():]

        if person_names or excluded_person_names:
            text = _PERSON_FILLER_PATTERN.sub("", text)

    # Removing tokens from the middle of the string can leave doubled
    # or trailing whitespace behind — collapse it.
    text = re.sub(r"\s+", " ", text).strip()

    return ParsedQuery(
        text=text,
        year=year,
        month=month,
        season=season,
        person_names=person_names,
        excluded_person_names=excluded_person_names,
    )