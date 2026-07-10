"""Chunk storage and materialization."""

import sqlite3
import json
from abc import ABC, abstractmethod
from typing import List

from ..models import Chunk


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
        conn = sqlite3.connect(self.db_path)
        try:
            with conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS chunks (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT,
                        text TEXT,
                        metadata TEXT
                    )
                """)
        finally:
            conn.close()

    def get_chunks(self, chunk_ids: List[str]) -> List[Chunk]:
        if not chunk_ids:
            return []

        chunks = []
        placeholders = ",".join(["?"] * len(chunk_ids))
        query = f"SELECT chunk_id, document_id, text, metadata FROM chunks WHERE chunk_id IN ({placeholders})"

        try:
            conn = sqlite3.connect(self.db_path)
            try:
                cursor = conn.execute(query, chunk_ids)
                for row in cursor:
                    chunk_id, document_id, text, metadata_json = row

                    try:
                        metadata = json.loads(metadata_json) if metadata_json else {}
                    except json.JSONDecodeError:
                        metadata = {}

                    chunks.append(Chunk(
                        chunk_id=chunk_id,
                        document_id=document_id,
                        text=text,
                        embedding=None,
                        metadata=metadata
                    ))
            finally:
                conn.close()
        except sqlite3.Error as e:
            print(f"ChunkStore retrieval failed: {e}")

        return chunks
