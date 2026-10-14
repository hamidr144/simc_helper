"""Password hashing and simple in-memory rate limiting (stdlib only).

Password storage
----------------
New hashes use salted PBKDF2-HMAC-SHA256 (``hashlib.pbkdf2_hmac``), stored in
a self-describing string::

    pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>

Legacy hashes (unsalted ``sha256(password).hexdigest()``, 64 hex chars) are
still accepted by :func:`verify_password` so existing accounts keep working;
callers should upgrade them transparently on successful login via
:func:`password_needs_rehash`.

Rate limiting
-------------
:class:`RateLimiter` is a small sliding-window, per-key counter modelled on
the in-memory state pattern of ``src/core/circuit_breaker.py``.  It is
process-local by design (single master process); restarts clear it.
"""

import hashlib
import hmac
import secrets
import time
from collections import deque
from typing import Deque, Dict, Optional

PBKDF2_ITERATIONS = 240_000  # OWASP guidance for PBKDF2-HMAC-SHA256 (2023+)
_PBKDF2_PREFIX = "pbkdf2_sha256"
_LEGACY_SHA256_LEN = 64
_HEX_CHARS = set("0123456789abcdef")


def hash_password(password: str) -> str:
    """Return a salted PBKDF2-HMAC-SHA256 hash for *password*."""
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), PBKDF2_ITERATIONS
    ).hex()
    return f"{_PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest}"


def _is_legacy_sha256(stored: str) -> bool:
    return (
        len(stored) == _LEGACY_SHA256_LEN
        and stored[0] in _HEX_CHARS
        and all(c in _HEX_CHARS for c in stored)
    )


def verify_password(password: str, stored: str) -> bool:
    """Check *password* against a stored hash (PBKDF2 or legacy SHA-256)."""
    if not stored:
        return False
    if stored.startswith(_PBKDF2_PREFIX + "$"):
        parts = stored.split("$")
        if len(parts) != 4:
            return False
        try:
            iterations = int(parts[1])
            salt = bytes.fromhex(parts[2])
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, iterations
        ).hex()
        return hmac.compare_digest(digest, parts[3])
    if _is_legacy_sha256(stored):
        legacy = hashlib.sha256(password.encode("utf-8")).hexdigest()
        return hmac.compare_digest(legacy, stored)
    return False


def password_needs_rehash(stored: str) -> bool:
    """True when *stored* is a legacy hash or uses fewer iterations than now."""
    if not stored.startswith(_PBKDF2_PREFIX + "$"):
        return True
    parts = stored.split("$")
    if len(parts) != 4:
        return True
    try:
        return int(parts[1]) < PBKDF2_ITERATIONS
    except ValueError:
        return True


class RateLimiter:
    """Sliding-window per-key event limiter.

    ``record(key)`` logs one event; ``is_limited(key)`` returns True once more
    than ``max_events`` have been recorded within the trailing
    ``window_seconds``.  Memory is bounded: keys expire with their window and
    the per-key deque is capped at ``max_events + 1`` timestamps.
    """

    def __init__(self, max_events: int, window_seconds: float):
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._events: Dict[str, Deque[float]] = {}

    def _prune(self, key: str, now: float) -> Optional[Deque[float]]:
        events = self._events.get(key)
        if not events:
            return None
        cutoff = now - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._events.pop(key, None)
            return None
        return events

    def record(self, key: str, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        events = self._events.setdefault(key, deque())
        events.append(now)
        self._prune(key, now)

    def is_limited(self, key: str, now: Optional[float] = None) -> bool:
        now = time.monotonic() if now is None else now
        events = self._prune(key, now)
        return events is not None and len(events) >= self.max_events

    def retry_after(self, key: str, now: Optional[float] = None) -> int:
        """Seconds until the oldest event leaves the window (0 when not limited)."""
        now = time.monotonic() if now is None else now
        events = self._prune(key, now)
        if events is None or len(events) < self.max_events:
            return 0
        return max(1, int(self.window_seconds - (now - events[0])) + 1)

    def reset(self, key: Optional[str] = None) -> None:
        if key is None:
            self._events.clear()
        else:
            self._events.pop(key, None)
