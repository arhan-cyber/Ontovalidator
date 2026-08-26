"""PDF ingestion: per-page text and tables with page/section provenance.

Page-level provenance is the whole point of this module. A grounding
finding is only actionable if it can cite "wb_incident_management.pdf p.7
section 1.4.1" rather than just "somewhere in the corpus". `PDFExtractor`
walks a PDF with pdfplumber, maintains a heading stack while it goes, and
tags every text segment and table it emits with
`{source_file, page, section_path}`.

Table and list parsing are deliberately NOT reimplemented here -- extracted
tables are converted to a small HTML fragment and handed to the existing
`TableExtractor`, and page text is handed to the existing `ListExtractor`,
so both modalities go through one code path regardless of whether they came
from a PDF or a plain-text document.
"""

import os
import re
from dataclasses import dataclass, field
from html import escape
from typing import Any, Dict, List, Optional, Tuple


class PDFExtractionError(Exception):
    """Raised when a PDF cannot be opened or read (missing/encrypted/corrupt/empty)."""


# ---------------------------------------------------------------------------
# Heading-stack logic. Kept free of any pdfplumber/PDF dependency so it can
# be unit-tested against plain strings.
# ---------------------------------------------------------------------------

# Matches lines like "1.5 Process Principles", "1. Introduction",
# "4.2.3. Contract Definition", "1.4.1 Objectives". The title must start
# with an uppercase letter and must not itself read like a sentence (which
# is how numbered action items such as "1.4.1.5 Invoke the Problem
# Management process to identify..." are told apart from real headings):
# a real heading is short and does not end in sentence punctuation.
_HEADING_RE = re.compile(r"^(\d+(?:\.\d+){0,5})\.?\s+([A-Z].{0,89})$")
_MAX_TITLE_LEN = 90
_SENTENCE_ENDINGS = (".", ",", ";", ":")


class HeadingStack:
    """Tracks the current numbered-section path as lines are fed to it.

    This is the reusable, PDF-free core of the heading logic: `update()`
    takes one line of text at a time and returns whether it recognised a
    heading; `path()` renders the current stack as a "1.4 Process
    Objectives > 1.4.1 Objectives"-style string, or `None` if no heading has
    been seen yet. Callers must not invent a section_path when this
    returns `None` -- that is the graceful fallback the ingestion pipeline
    relies on for front matter, cover pages, etc.
    """

    def __init__(self) -> None:
        # Each entry: (depth, number, title)
        self._stack: List[Tuple[int, str, str]] = []

    @staticmethod
    def match_heading(line: str) -> Optional[Tuple[str, str]]:
        """Return (number, title) if `line` looks like a numbered heading, else None."""
        stripped = (line or "").strip()
        if not stripped:
            return None
        match = _HEADING_RE.match(stripped)
        if not match:
            return None
        number, title = match.group(1), match.group(2).strip()
        if not title or len(title) > _MAX_TITLE_LEN:
            return None
        if title.endswith(_SENTENCE_ENDINGS):
            return None
        return number, title

    def update(self, line: str) -> bool:
        """Feed one line; update the stack in place if it is a heading.

        Returns True iff the stack changed.
        """
        matched = self.match_heading(line)
        if not matched:
            return False
        number, title = matched
        depth = number.count(".") + 1
        while self._stack and self._stack[-1][0] >= depth:
            self._stack.pop()
        self._stack.append((depth, number, title))
        return True

    def path(self) -> Optional[str]:
        """Current section path, or None if no heading has been seen yet."""
        if not self._stack:
            return None
        return " > ".join(f"{num} {title}" for _, num, title in self._stack)

    def snapshot(self) -> List[Tuple[int, str, str]]:
        return list(self._stack)


# ---------------------------------------------------------------------------
# Extracted content shapes
# ---------------------------------------------------------------------------


@dataclass
class PDFSegment:
    """A run of prose text on one page, scoped to whatever heading precedes it."""

    page: int
    section_path: Optional[str]
    text: str


@dataclass
class PDFTable:
    """A table found on one page, as an HTML fragment ready for `TableExtractor`."""

    page: int
    section_path: Optional[str]
    html: str
    table_index: int


@dataclass
class PDFDocument:
    source_file: str
    segments: List[PDFSegment] = field(default_factory=list)
    tables: List[PDFTable] = field(default_factory=list)


def _table_rows_to_html(rows: List[List[Optional[str]]]) -> str:
    """Render a pdfplumber table (list of rows of cells) as a minimal HTML table."""
    if not rows:
        return ""
    lines = ["<table>"]
    for row_idx, row in enumerate(rows):
        tag = "th" if row_idx == 0 else "td"
        cells = "".join(f"<{tag}>{escape((cell or '').strip())}</{tag}>" for cell in row)
        lines.append(f"<tr>{cells}</tr>")
    lines.append("</table>")
    return "".join(lines)


class PDFExtractor:
    """Extracts per-page text and tables from a PDF with page/section provenance.

    Usage:
        extractor = PDFExtractor()
        doc = extractor.extract(path, page_range=(1, 10))
        # doc.segments -> List[PDFSegment], doc.tables -> List[PDFTable]
    """

    def __init__(self):
        pass

    def extract(self, path: str, page_range: Optional[Tuple[int, int]] = None) -> PDFDocument:
        """Extract `path` into page-scoped text segments and tables.

        `page_range` is a 1-indexed, inclusive `(start, end)` tuple. Needed
        for the 294-page IT4IT standard, where callers typically only want
        a handful of pages.

        Raises `PDFExtractionError` (never a bare traceback) for a missing
        file, an encrypted/password-protected PDF, a corrupt file, or a PDF
        with zero pages.
        """
        if not os.path.exists(path):
            raise PDFExtractionError(f"PDF not found at {path}")

        try:
            import pdfplumber
        except ImportError as exc:
            raise PDFExtractionError(
                "pdfplumber is not installed; add it via requirements-ml.txt"
            ) from exc

        try:
            pdf = pdfplumber.open(path)
        except Exception as exc:
            raise PDFExtractionError(f"Could not open PDF at {path}: {type(exc).__name__}: {exc}") from exc

        try:
            with pdf:
                total_pages = len(pdf.pages)
                if total_pages == 0:
                    raise PDFExtractionError(f"PDF at {path} has zero pages")

                start, end = self._resolve_range(page_range, total_pages)
                source_file = os.path.basename(path)
                doc = PDFDocument(source_file=source_file)
                heading_stack = HeadingStack()

                for page_num in range(start, end + 1):
                    page = pdf.pages[page_num - 1]
                    self._extract_page(page, page_num, heading_stack, doc)

                return doc
        except PDFExtractionError:
            raise
        except Exception as exc:
            raise PDFExtractionError(f"Failed reading PDF at {path}: {type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _resolve_range(page_range: Optional[Tuple[int, int]], total_pages: int) -> Tuple[int, int]:
        if page_range is None:
            return 1, total_pages
        start, end = page_range
        start = max(1, int(start))
        end = min(total_pages, int(end))
        if start > end:
            raise PDFExtractionError(
                f"Invalid page_range {page_range} for a document with {total_pages} pages"
            )
        return start, end

    def _extract_page(self, page, page_num: int, heading_stack: HeadingStack, doc: PDFDocument) -> None:
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""

        buffer: List[str] = []
        current_path = heading_stack.path()

        def _flush():
            if buffer:
                joined = "\n".join(buffer).strip()
                if joined:
                    doc.segments.append(PDFSegment(page=page_num, section_path=current_path, text=joined))
                buffer.clear()

        for line in text.split("\n"):
            if heading_stack.update(line):
                _flush()
                current_path = heading_stack.path()
                continue
            buffer.append(line)
        _flush()

        # Tables are returned by pdfplumber in top-to-bottom document order
        # but without a common coordinate space against the text lines, so
        # a table is conservatively tagged with the section reached by the
        # end of the page's text rather than an exact position -- this can
        # misattribute a table that appears before the page's last heading,
        # but never invents a section that wasn't seen on the page.
        end_of_page_path = heading_stack.path()
        try:
            tables = page.extract_tables() or []
        except Exception:
            tables = []
        for idx, rows in enumerate(tables):
            html = _table_rows_to_html(rows)
            if html:
                doc.tables.append(
                    PDFTable(page=page_num, section_path=end_of_page_path, html=html, table_index=idx)
                )


__all__ = ["PDFExtractor", "PDFExtractionError", "HeadingStack", "PDFDocument", "PDFSegment", "PDFTable"]
