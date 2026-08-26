"""Shared SQLite connection helper.

Every `sqlite3.connect(...)` call in this codebase used to be bare: no
`timeout=`, no `busy_timeout` pragma, no WAL mode. SQLite defaults to
rollback-journal mode with exclusive-write locking, so a bare connect fails
fast with `database is locked` under any write contention instead of
waiting/retrying. This matters here because all pooled engine variants
(api/dependencies.py) share one physical DB file, so concurrent requests are
concurrent writers to the same SQLite file.

`connect()` opts every caller into a bounded wait (busy_timeout) and WAL mode
(readers don't block writers), which is a much better default for a
multi-request server than SQLite's factory default.
"""

import sqlite3

DEFAULT_BUSY_TIMEOUT_S = 30.0


def connect(db_path: str, timeout_s: float = DEFAULT_BUSY_TIMEOUT_S) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path, timeout=timeout_s)
    # PRAGMA doesn't reliably accept bound `?` parameters across sqlite3
    # versions; timeout_s is never user input, so inlining it is safe.
    conn.execute(f"PRAGMA busy_timeout = {int(timeout_s * 1000)}")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn
