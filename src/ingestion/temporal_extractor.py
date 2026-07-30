"""Extracts dates and time expressions so evidence can be placed on a timeline."""

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}

# Historical medical/legal sources routinely cite 19th-century dates, so the
# year range starts at 1800 rather than 1900.
_YEAR = r"1[89]\d{2}|20\d{2}"

_ISO = re.compile(rf"\b(?P<year>{_YEAR})-(?P<month>\d{{1,2}})-(?P<day>\d{{1,2}})\b")
_MONTH_NAME = re.compile(
    r"\b(?P<month>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+"
    rf"(?P<day>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<year>{_YEAR})\b",
    re.IGNORECASE,
)
_SLASHED = re.compile(rf"\b(?P<day>\d{{1,2}})/(?P<month>\d{{1,2}})/(?P<year>{_YEAR})\b")
_YEAR_ONLY = re.compile(rf"\b(?P<year>{_YEAR})\b")

# Ordered most specific first: a full date should not also be read as a bare year.
DATE_PATTERNS = (_ISO, _MONTH_NAME, _SLASHED, _YEAR_ONLY)

TEMPORAL_EXPRESSIONS = (
    (r"\b(recently|lately|currently|nowadays|today|these days)\b", "recent"),
    (r"\bin the (\d{2,4})s\b", "decade"),
    (r"\b(\d+) years? ago\b", "relative"),
    (rf"\b(since|until|before|after) ({_YEAR})\b", "bounded"),
)

DOCUMENT_DATE_PATTERNS = (
    r"(?:Updated|Published|Written|Revised|Date)\s*:\s*(\d{4}-\d{1,2}-\d{1,2})",
    r"(?:Updated|Published|Written|Revised|Date)\s*:\s*([A-Za-z]+\.?\s+\d{1,2},?\s+\d{4})",
)


class TemporalExtractor:
    """Finds absolute dates, relative time expressions, and a document's own date."""

    def extract_dates(self, text: str) -> List[datetime]:
        """All dates mentioned in `text`, in order, without double-counting."""
        dates: List[datetime] = []
        consumed: List[range] = []

        for pattern in DATE_PATTERNS:
            for match in pattern.finditer(text or ""):
                start, end = match.span()
                if any(start in span for span in consumed):
                    continue
                # Claim the span either way: an impossible date like 45/13/2020
                # must not fall through and be re-read as the bare year 2020.
                consumed.append(range(start, end))
                parsed = self._parse_match(match)
                if parsed is not None:
                    dates.append(parsed)

        return sorted(dates)

    def _parse_match(self, match: re.Match) -> Optional[datetime]:
        groups = match.groupdict()
        try:
            year = int(groups["year"])
        except (KeyError, TypeError, ValueError):
            return None

        month_raw = groups.get("month")
        if month_raw is None:
            month = 1
        elif month_raw.isdigit():
            month = int(month_raw)
        else:
            month = MONTHS.get(month_raw[:3].lower(), 1)

        day = int(groups["day"]) if groups.get("day") else 1
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    def extract_temporal_expressions(self, text: str) -> List[Dict[str, Any]]:
        """Relative phrases like 'recently' or 'in the 1990s' with their offsets."""
        results = []
        for pattern, kind in TEMPORAL_EXPRESSIONS:
            for match in re.finditer(pattern, text or "", re.IGNORECASE):
                results.append({
                    "text": match.group(0),
                    "type": kind,
                    "span": list(match.span()),
                })
        results.sort(key=lambda item: item["span"][0])
        return results

    def infer_document_date(self, text: str) -> Optional[datetime]:
        """Date from an explicit 'Published:'/'Updated:' style header, if present."""
        for pattern in DOCUMENT_DATE_PATTERNS:
            match = re.search(pattern, text or "", re.IGNORECASE)
            if match:
                parsed = self._parse_date_string(match.group(1))
                if parsed:
                    return parsed
        return None

    def _parse_date_string(self, value: str) -> Optional[datetime]:
        for pattern in DATE_PATTERNS:
            match = pattern.search(value)
            if match:
                parsed = self._parse_match(match)
                if parsed:
                    return parsed
        return None

    def describe(self, text: str, document_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Full temporal metadata payload attached to an ingested chunk."""
        dates = self.extract_dates(text)
        return {
            "mentioned_dates": [d.isoformat() for d in dates],
            "temporal_expressions": self.extract_temporal_expressions(text),
            "document_date": document_date.isoformat() if document_date else None,
        }


__all__ = ["TemporalExtractor", "DATE_PATTERNS", "TEMPORAL_EXPRESSIONS"]
