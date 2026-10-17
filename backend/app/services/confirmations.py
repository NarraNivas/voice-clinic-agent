"""Server-issued confirmation tokens for writes.

A write happens only when the caller sends back a token the server issued for a preview of the
same operation and the same details. Tokens are random, stored as SHA-256 hashes, expire after
five minutes, and work once. A boolean flag in the request is not enough.
"""

import hashlib
import json
import secrets
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from app.services.errors import ApiError

TOKEN_TTL = timedelta(minutes=5)


def digest(operation: str, details: dict[str, Any]) -> str:
    """Stable fingerprint of one operation and its details. Changing any detail changes it."""
    canonical = json.dumps({"operation": operation, "details": details}, sort_keys=True)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(conn: sqlite3.Connection, *, operation: str, details_digest: str, now: datetime) -> str:
    token = secrets.token_urlsafe(24)
    conn.execute(
        """
        INSERT INTO pending_confirmations (token_hash, operation, details_digest, expires_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            _hash_token(token),
            operation,
            details_digest,
            (now + TOKEN_TTL).isoformat(timespec="seconds"),
        ),
    )
    return token


def consume(
    conn: sqlite3.Connection,
    *,
    token: str,
    operation: str,
    details_digest: str,
    now: datetime,
) -> None:
    """Mark a token used. Call inside the same write transaction as the change it authorises.

    Unknown, reused, mismatched, and expired tokens all fail. The error does not say which,
    so a caller cannot probe for valid tokens.
    """
    row = conn.execute(
        """
        SELECT operation, details_digest, expires_at, used_at
        FROM pending_confirmations WHERE token_hash = ?
        """,
        (_hash_token(token),),
    ).fetchone()
    if (
        row is None
        or row["used_at"] is not None
        or row["operation"] != operation
        or row["details_digest"] != details_digest
    ):
        raise ApiError(
            "invalid_confirmation",
            "That confirmation is not valid for these details. Review the change and try again.",
            status_code=409,
        )
    if datetime.fromisoformat(row["expires_at"]) < now:
        raise ApiError(
            "confirmation_expired",
            "That confirmation expired. Review the change and try again.",
            status_code=409,
        )
    conn.execute(
        "UPDATE pending_confirmations SET used_at = ? WHERE token_hash = ?",
        (now.isoformat(timespec="seconds"), _hash_token(token)),
    )
