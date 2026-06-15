import os
import sqlite3
import uuid
import time
import sys
from typing import Any, Dict, Optional

# Determine PROJECT_ROOT
if hasattr(sys, 'frozen'):
    # If running as a PyInstaller bundle
    base_path = os.path.dirname(sys.executable)
    PROJECT_ROOT = os.path.abspath(os.path.join(base_path, ".."))
else:
    # If running normally
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))

# Fallback check
if not os.path.exists(PROJECT_ROOT) or not os.path.exists(os.path.join(PROJECT_ROOT, "src")):
    PROJECT_ROOT = os.path.abspath(os.path.join(PROJECT_ROOT, ".."))
    if not os.path.exists(PROJECT_ROOT) or not os.path.exists(os.path.join(PROJECT_ROOT, "src")):
        # Last resort: try to find where 'src' is relative to current file
        # This is just a safety net
        PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, "..", ".."))

# Ensure DB directory exists
db_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "master"))
os.makedirs(db_dir, exist_ok=True)

_DB_PATH = os.path.abspath(os.path.join(db_dir, "simc_helper.sqlite"))
print(f"DEBUG: DB_PATH is {_DB_PATH}")

def get_db_path() -> str:
    """Return the absolute path to the SQLite database file."""
    return os.path.abspath(_DB_PATH)

def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode and short timeout for concurrency."""
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn

def init_db() -> None:
    """Create tables if they do not exist. Idempotent – safe to call multiple times."""
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                user_id       TEXT PRIMARY KEY,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at    REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_sessions (
                user_id       TEXT PRIMARY KEY,
                last_sim_time REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS user_inputs (
                user_id     TEXT PRIMARY KEY,
                input_id    TEXT    NOT NULL,
                file_path   TEXT    NOT NULL,
                input_url   TEXT    NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# users  (wraps account management)
# ---------------------------------------------------------------------------

def user_get(username: str) -> Optional[Dict[str, Any]]:
    """Return the user record for *username*, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT user_id, username, password_hash, created_at FROM users WHERE username = ?", (username,)
        ).fetchone()
        if row is None:
            return None
        return {
            "user_id": row[0],
            "username": row[1],
            "password_hash": row[2],
            "created_at": row[3],
        }
    finally:
        conn.close()

def user_create(username: str, password_hash: str) -> str:
    """Create a new user and return their *user_id*. Raises Exception if username exists."""
    conn = _connect()
    try:
        user_id = uuid.uuid4().hex
        created_at = time.time()
        conn.execute(
            "INSERT INTO users (user_id, username, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (user_id, username, password_hash, created_at),
        )
        conn.execute(
            "INSERT INTO user_sessions (user_id, last_sim_time) VALUES (?, ?)",
            (user_id, 0.0),
        )
        conn.commit()
        return user_id
    finally:
        conn.close()

def user_delete(user_id: str) -> None:
    """Remove the user record for *user_id*."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM users WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# user_sessions  (wraps user_last_sim_time)
# ---------------------------------------------------------------------------

def session_get(user_id: str) -> Optional[float]:
    """Return last_sim_time for *user_id*, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT last_sim_time FROM user_sessions WHERE user_id = ?", (user_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def session_set(user_id: str, timestamp: float) -> None:
    """Record / update the last simulation time for *user_id*."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO user_sessions (user_id, last_sim_time) VALUES (?, ?)",
            (user_id, timestamp),
        )
        conn.commit()
    finally:
        conn.close()

def session_delete(user_id: str) -> None:
    """Remove the session record for *user_id*."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM user_sessions WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def session_cleanup_older_than(seconds: float, now: float) -> list[str]:
    """Return (and delete) user_ids whose last_sim_time is older than *seconds*."""
    cutoff = now - seconds
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT user_id FROM user_sessions WHERE last_sim_time < ?", (cutoff,)
        ).fetchall()
        ids = [r[0] for r in rows]
        if ids:
            placeholders = ",".join("?" * len(ids))
            conn.execute(
                f"DELETE FROM user_sessions WHERE user_id IN ({placeholders})", ids
            )
            conn.commit()
        return ids
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# user_inputs  (wraps generated_inputs_by_user)
# ---------------------------------------------------------------------------

def input_get(user_id: str) -> Optional[Dict[str, Any]]:
    """Return the input record for *user_id*, or None if not found."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT input_id, file_path, input_url FROM user_inputs WHERE user_id = ?",
            (user_id,)
        ).fetchone()
        if row is None:
            return None
        return {
            "input_id": row[0],
            "file_path": row[1],
            "input_url": row[2],
        }
    finally:
        conn.close()

def input_set(user_id: str, record: Dict[str, Any]) -> None:
    """Persist an input record for *user_id*."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO user_inputs (user_id, input_id, file_path, input_url) VALUES (?, ?, ?, ?)",
            (user_id, record["input_id"], record["file_path"], record["input_url"]),
        )
        conn.commit()
    finally:
        conn.close()

def input_delete(user_id: str) -> None:
    """Remove the input record for *user_id*."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM user_inputs WHERE user_id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()

def load_sessions() -> Dict[str, float]:
    """Return all sessions as {user_id: last_sim_time}.
    Called once at startup to restore in-memory state."""
    conn = _connect()
    try:
        rows = conn.execute("SELECT user_id, last_sim_time FROM user_sessions").fetchall()
        return {r[0]: r[1] for r in rows}
    finally:
        conn.close()

def load_inputs() -> Dict[str, Dict[str, Any]]:
    """Return all input records as {user_id: record}.
    Called once at startup to restore in-memory state."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT user_id, input_id, file_path, input_url FROM user_inputs"
        ).fetchall()
        return {
            r[0]: {"input_id": r[1], "file_path": r[2], "input_url": r[3]}
            for r in rows
        }
    finally:
        conn.close()
