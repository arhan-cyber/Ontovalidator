"""Splits bulleted and numbered lists into one chunk per item."""

import re
from typing import Any, Dict, List

from ..models import ChunkType


class ListExtractor:
    """Extracts list items as separate chunks.

    Sentence chunking keeps a whole list glued to its lead-in sentence, which
    buries individual items; pulling each item out gives retrieval something
    short and self-contained to match.
    """

    LIST_PATTERNS = [
        (r"^\s*[-•*]\s+(.+)$", "bullet"),
        (r"^\s*\d+[.)]\s+(.+)$", "numbered"),
        (r"^\s*[a-zA-Z][.)]\s+(.+)$", "lettered"),
    ]

    MIN_ITEM_LENGTH = 2

    def extract_from_text(self, text: str) -> List[Dict[str, Any]]:
        chunks: List[Dict[str, Any]] = []
        for line_num, line in enumerate((text or "").split("\n")):
            for pattern, kind in self.LIST_PATTERNS:
                match = re.match(pattern, line)
                if not match:
                    continue
                item_text = match.group(1).strip()
                if len(item_text) >= self.MIN_ITEM_LENGTH:
                    chunks.append({
                        "type": ChunkType.LIST_ITEM,
                        "text": item_text,
                        "type_metadata": {
                            "original_line": line,
                            "line_num": line_num,
                            "list_style": kind,
                        },
                    })
                break
        return chunks


__all__ = ["ListExtractor"]
