"""SQLite writes under real concurrency should not deadlock or fail fast.

Every connect() in this codebase now goes through src.storage.sqlite_conn,
which sets a busy_timeout and WAL mode instead of leaving SQLite's bare
rollback-journal defaults (exclusive-write locking, no retry) in place.
"""

import os
import sqlite3
import tempfile
import threading

from src.storage.sqlite_conn import connect


def test_connect_enables_wal_and_busy_timeout():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = connect(db_path, timeout_s=5.0)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
            timeout_ms = conn.execute("PRAGMA busy_timeout").fetchone()[0]
            assert timeout_ms == 5000
        finally:
            conn.close()


def test_concurrent_writers_do_not_fail_fast(tmp_workspace):
    from src.storage import SQLiteChunkStore, ensure_chunks_schema

    db_path = os.path.join(tmp_workspace, "concurrent.db")
    SQLiteChunkStore(db_path)  # creates schema

    errors = []
    n_threads = 20

    def write_one(i):
        try:
            conn = connect(db_path, timeout_s=10.0)
            try:
                with conn:
                    conn.execute(
                        "INSERT INTO chunks (chunk_id, document_id, text, metadata) VALUES (?, ?, ?, ?)",
                        (f"chunk_{i}", f"doc_{i}", f"text {i}", "{}"),
                    )
            finally:
                conn.close()
        except sqlite3.Error as e:
            errors.append((i, str(e)))

    threads = [threading.Thread(target=write_one, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)

    assert not any(t.is_alive() for t in threads), "a writer thread hung past the busy_timeout"
    assert errors == [], f"unexpected write failures under concurrency: {errors}"

    conn = connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    finally:
        conn.close()
    assert count == n_threads
