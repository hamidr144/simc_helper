import os
import sqlite3
import sys
import time
import uuid
from typing import Any, Dict, Optional

# Deployed binaries receive BASE_DIR from the deployer. When it is not set,
# derive the project root from the executable (frozen) or source tree (dev).
configured_base_dir = os.environ.get("BASE_DIR")
if configured_base_dir:
    PROJECT_ROOT = os.path.abspath(os.path.expanduser(configured_base_dir))
elif getattr(sys, "frozen", False):
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(sys.executable), ".."))
else:
    module_dir = os.path.dirname(os.path.abspath(__file__))
    PROJECT_ROOT = os.path.abspath(os.path.join(module_dir, "..", ".."))

# Ensure DB directory exists
db_dir = os.path.abspath(os.path.join(PROJECT_ROOT, "data", "master"))
os.makedirs(db_dir, exist_ok=True)

_DB_PATH = os.path.abspath(os.path.join(db_dir, "simc_helper.sqlite"))

def get_db_path() -> str:
    """Return the absolute path to the SQLite database file."""
    return os.path.abspath(_DB_PATH)

def _connect() -> sqlite3.Connection:
    """Open a connection with WAL mode and short timeout for concurrency."""
    conn = sqlite3.connect(_DB_PATH, timeout=5)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    # t_b3b78acd: enforce FKs so run_history's ON DELETE CASCADE actually fires
    # when a user is deleted (SQLite defaults this off per-connection).
    conn.execute("PRAGMA foreign_keys=ON")
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

            CREATE TABLE IF NOT EXISTS auth_sessions (
                token      TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_auth_sessions_expires
                ON auth_sessions (expires_at);

            CREATE TABLE IF NOT EXISTS user_inputs (
                user_id     TEXT PRIMARY KEY,
                input_id    TEXT    NOT NULL,
                file_path   TEXT    NOT NULL,
                input_url   TEXT    NOT NULL
            );

            CREATE TABLE IF NOT EXISTS run_history (
                run_id         TEXT PRIMARY KEY,
                user_id        TEXT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                created_at     REAL NOT NULL,
                fighting_style TEXT,
                spec           TEXT,
                source         TEXT,
                char_name      TEXT,
                realm_slug     TEXT,
                region         TEXT,
                top_dps        INTEGER,
                report_path    TEXT,
                status         TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_run_history_user_created
                ON run_history (user_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS task_owner (
                task_id    TEXT PRIMARY KEY,
                user_id    TEXT NOT NULL,
                meta       TEXT,
                created_at REAL NOT NULL
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

# ---------------------------------------------------------------------------
# auth_sessions  (SEC-7 t_0e328148: opaque server-side session tokens)
# ---------------------------------------------------------------------------

def auth_session_create(token: str, user_id: str, expires_at: float) -> None:
    """Register an issued session token for *user_id*."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT INTO auth_sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, time.time(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()

def auth_session_user(token: str, now: float) -> Optional[Dict[str, Any]]:
    """Return the user record owning a valid (unexpired) session token."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT u.user_id, u.username, u.password_hash, u.created_at "
            "FROM auth_sessions s JOIN users u ON u.user_id = s.user_id "
            "WHERE s.token = ? AND s.expires_at > ?",
            (token, now),
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

def auth_session_delete(token: str) -> None:
    """Revoke one session token (logout); other devices keep their sessions."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM auth_sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()

def auth_session_purge_expired(now: float) -> None:
    """Drop expired session rows (housekeeping, called on login)."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM auth_sessions WHERE expires_at <= ?", (now,))
        conn.commit()
    finally:
        conn.close()

def user_set_password_hash(user_id: str, password_hash: str) -> None:
    """Overwrite the stored password hash for *user_id* (legacy-hash upgrade)."""
    conn = _connect()
    try:
        conn.execute(
            "UPDATE users SET password_hash = ? WHERE user_id = ?", (password_hash, user_id)
        )
        conn.commit()
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

# ---------------------------------------------------------------------------
# run_history  (t_b3b78acd: durable per-user simulation results history)
# ---------------------------------------------------------------------------

def run_history_insert(record: Dict[str, Any]) -> str:
    """Insert one run-history row and return its ``run_id``.

    ``record`` keys: run_id, user_id, created_at, status (required);
    fighting_style, spec, source, char_name, realm_slug, region, top_dps,
    report_path (optional, None allowed). Raises sqlite3.IntegrityError when
    *user_id* does not reference an existing user (FK) — callers that record
    best-effort (e.g. the SSE done hook for anonymous users) should catch it.
    """
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO run_history (
                run_id, user_id, created_at, fighting_style, spec, source,
                char_name, realm_slug, region, top_dps, report_path, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record["run_id"], record["user_id"], record["created_at"],
                record.get("fighting_style"), record.get("spec"), record.get("source"),
                record.get("char_name"), record.get("realm_slug"), record.get("region"),
                record.get("top_dps"), record.get("report_path"), record["status"],
            ),
        )
        conn.commit()
        return record["run_id"]
    finally:
        conn.close()

def run_history_list(user_id: str, limit: int = 50) -> list[Dict[str, Any]]:
    """Return the newest *limit* runs for *user_id* (newest first)."""
    conn = _connect()
    try:
        rows = conn.execute(
            """
            SELECT run_id, user_id, created_at, fighting_style, spec, source,
                   char_name, realm_slug, region, top_dps, report_path, status
            FROM run_history
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [
            {
                "run_id": r[0], "user_id": r[1], "created_at": r[2],
                "fighting_style": r[3], "spec": r[4], "source": r[5],
                "char_name": r[6], "realm_slug": r[7], "region": r[8],
                "top_dps": r[9], "report_path": r[10], "status": r[11],
            }
            for r in rows
        ]
    finally:
        conn.close()

def run_history_get(run_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    """Return one run row only when it belongs to *user_id* (t_d34ced81).

    Ownership is enforced in SQL so a caller can never leak another user's
    run by guessing a ``run_id`` — a miss and a foreign row both return
    ``None``.
    """
    conn = _connect()
    try:
        row = conn.execute(
            """
            SELECT run_id, user_id, created_at, fighting_style, spec, source,
                   char_name, realm_slug, region, top_dps, report_path, status
            FROM run_history
            WHERE run_id = ? AND user_id = ?
            """,
            (run_id, user_id),
        ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row[0], "user_id": row[1], "created_at": row[2],
            "fighting_style": row[3], "spec": row[4], "source": row[5],
            "char_name": row[6], "realm_slug": row[7], "region": row[8],
            "top_dps": row[9], "report_path": row[10], "status": row[11],
        }
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

# ---------------------------------------------------------------------------
# task_owner  (durable task_user_map / task_meta_map — LIFE-2, t_2c718ca6)
# ---------------------------------------------------------------------------

def task_owner_upsert(task_id: str, user_id: str, meta: Optional[str]) -> None:
    """Record (or refresh) the owner + run metadata for *task_id*."""
    conn = _connect()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO task_owner (task_id, user_id, meta, created_at)"
            " VALUES (?, ?, ?, ?)",
            (task_id, user_id, meta, time.time()),
        )
        conn.commit()
    finally:
        conn.close()

def task_owner_load() -> Dict[str, Dict[str, Any]]:
    """Return all owner records as {task_id: {"user_id":…, "meta":…}}.
    Called once at startup to restore in-memory state."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT task_id, user_id, meta FROM task_owner"
        ).fetchall()
        return {r[0]: {"user_id": r[1], "meta": r[2]} for r in rows}
    finally:
        conn.close()

def task_owner_meta_json(task_id: str) -> Optional[str]:
    """Return the persisted run-meta JSON string for *task_id* (None when
    unknown). TG3-G: /api/get-results reads the generation mode here because
    the done hook pops the in-memory task_meta_map before results are viewed.
    """
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT meta FROM task_owner WHERE task_id = ?", (task_id,)
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()

def task_owner_prune_older_than(cutoff: float) -> None:
    """Delete owner rows created before *cutoff* (runs finish in minutes;
    the row only needs to outlive a master restart, not a week)."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM task_owner WHERE created_at < ?", (cutoff,))
        conn.commit()
    finally:
        conn.close()
