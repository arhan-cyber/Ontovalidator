"""Turns tabular sources into one retrievable chunk per row."""

import csv
import io
import re
from html import unescape
from typing import Any, Dict, List, Optional

from ..models import ChunkType

_TAG_PATTERN = re.compile(r"<[^>]+>")
_ROW_PATTERN = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
_CELL_PATTERN = re.compile(r"<(t[hd])[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)


def _clean(cell_html: str) -> str:
    return unescape(_TAG_PATTERN.sub(" ", cell_html)).strip()


class TableExtractor:
    """Extracts structured data from tables without requiring pandas.

    Each row becomes its own chunk rendered as "Header: value | Header: value",
    so the existing text retrievers can match a query against a single row
    instead of a wall of table markup.
    """

    def extract_from_html(self, html_table: str, table_id: Optional[str] = None) -> List[Dict[str, Any]]:
        rows = _ROW_PATTERN.findall(html_table or "")
        if not rows:
            return []

        parsed = [[_clean(cell) for _, cell in _CELL_PATTERN.findall(row)] for row in rows]
        parsed = [row for row in parsed if any(cell for cell in row)]
        if len(parsed) < 2:
            return []

        headers = parsed[0]
        table_id = table_id or f"table_{abs(hash(html_table)) % (10 ** 8)}"
        return self._rows_to_chunks(headers, parsed[1:], table_id)

    def extract_from_csv(self, csv_path: str, table_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with open(csv_path, newline="", encoding="utf-8") as handle:
            return self.extract_from_csv_text(handle.read(), table_id or f"csv_{csv_path}")

    def extract_from_csv_text(self, csv_text: str, table_id: str = "csv") -> List[Dict[str, Any]]:
        reader = list(csv.reader(io.StringIO(csv_text)))
        rows = [row for row in reader if any(cell.strip() for cell in row)]
        if len(rows) < 2:
            return []
        return self._rows_to_chunks([c.strip() for c in rows[0]], rows[1:], table_id)

    def _rows_to_chunks(
        self,
        headers: List[str],
        rows: List[List[str]],
        table_id: str,
    ) -> List[Dict[str, Any]]:
        chunks = []
        for row_num, row in enumerate(rows):
            # Rows may be short or ragged; pair up what exists and keep the rest.
            values = {
                headers[i] if i < len(headers) else f"column_{i}": cell
                for i, cell in enumerate(row)
            }
            row_text = " | ".join(f"{key}: {value}" for key, value in values.items() if value)
            if not row_text:
                continue
            chunks.append({
                "type": ChunkType.TABLE_ROW,
                "text": row_text,
                "type_metadata": {
                    "table_id": table_id,
                    "row_num": row_num,
                    "headers": headers,
                    "values": values,
                },
            })
        return chunks


__all__ = ["TableExtractor"]
