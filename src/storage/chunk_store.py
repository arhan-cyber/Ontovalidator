"""Chunk storage and materialization."""

import sqlite3
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import List

from ..models import Chunk, ChunkType
from .sqlite_conn import connect as _connect

# Columns added after the original (chunk_id, document_id, text, metadata) schema.
# Existing databases are migrated in place with ALTER TABLE.
_EXTRA_COLUMNS = (
    ("chunk_type", "TEXT DEFAULT 'text'"),
    ("type_metadata", "TEXT"),
    ("timestamp", "TEXT"),
    ("temporal_metadata", "TEXT"),
)


def ensure_chunks_schema(conn: sqlite3.Connection) -> None:
    """Create the chunks table if missing and add any columns a legacy DB lacks."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chunks (
            chunk_id TEXT PRIMARY KEY,
            document_id TEXT,
            text TEXT,
            metadata TEXT
        )
    """)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(chunks)")}
    for name, decl in _EXTRA_COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE chunks ADD COLUMN {name} {decl}")


def row_to_chunk(row) -> Chunk:
    """Build a Chunk from a (chunk_id, document_id, text, metadata, chunk_type,
    type_metadata, timestamp, temporal_metadata) row."""
    chunk_id, document_id, text, metadata_json = row[:4]
    chunk_type_raw, type_metadata_json, timestamp_raw, temporal_json = (list(row[4:]) + [None] * 4)[:4]

    def _load(value):
        if not value:
            return None
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return None

    try:
        metadata = json.loads(metadata_json) if metadata_json else {}
    except json.JSONDecodeError:
        metadata = {}

    try:
        chunk_type = ChunkType(chunk_type_raw) if chunk_type_raw else ChunkType.TEXT
    except ValueError:
        chunk_type = ChunkType.TEXT

    timestamp = None
    if timestamp_raw:
        try:
            timestamp = datetime.fromisoformat(str(timestamp_raw))
        except ValueError:
            timestamp = None

    return Chunk(
        chunk_id=chunk_id,
        document_id=document_id,
        text=text,
        embedding=None,
        metadata=metadata,
        chunk_type=chunk_type,
        type_metadata=_load(type_metadata_json),
        timestamp=timestamp,
        temporal_metadata=_load(temporal_json),
    )


CHUNK_SELECT_COLUMNS = (
    "chunk_id, document_id, text, metadata, chunk_type, type_metadata, timestamp, temporal_metadata"
)


class ChunkStore(ABC):
    @abstractmethod
    def get_chunks(self, chunk_ids: List[str]) -> List[Chunk]:
        pass


class SQLiteChunkStore(ChunkStore):
    """SQLite-based chunk store for fast primary key lookups (late materialization)."""

    def __init__(self, db_path: str = "svo_data.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = _connect(self.db_path)
        try:
            with conn:
                ensure_chunks_schema(conn)
        finally:
            conn.close()

    def get_chunks(self, chunk_ids: List[str]) -> List[Chunk]:
        if not chunk_ids:
            return []

        chunks = []
        placeholders = ",".join(["?"] * len(chunk_ids))
        query = f"SELECT {CHUNK_SELECT_COLUMNS} FROM chunks WHERE chunk_id IN ({placeholders})"

        try:
            conn = _connect(self.db_path)
            try:
                cursor = conn.execute(query, chunk_ids)
                for row in cursor:
                    chunks.append(row_to_chunk(row))
            finally:
                conn.close()
        except sqlite3.Error as e:
            print(f"ChunkStore retrieval failed: {e}")

        return chunks
