"""Server-issued confirmation tokens for writes.

A write happens only when the caller sends back a token the server issued for a preview of the
same operation and the same details. Tokens are random, stored as SHA-256 hashes, expire after
five minutes, and work once.

Two extra rules make the token safe to retry and safe against stale previews:

- The token records the appointment revision the caller reviewed. If the booking has changed
  since, the token no longer matches, so a stale cancellation cannot act on a rescheduled booking.
- The outcome of a confirmed token is stored. Sending the same token again returns that outcome
  without writing anything, as long as the booking is still in the state the outcome describes.

A token proves that the same preview was confirmed. It does not prove that a person consented
to anything beyond that preview.
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


def _invalid() -> ApiError:
    return ApiError(
        "invalid_confirmation",
        "That confirmation is not valid for these details. Review the change and try again.",
        status_code=409,
    )


def issue(
    conn: sqlite3.Connection,
    *,
    operation: str,
    details_digest: str,
    preview_revision: int,
    now: datetime,
) -> str:
    token = secrets.token_urlsafe(24)
    conn.execute(
        """
        INSERT INTO pending_confirmations
            (token_hash, operation, details_digest, preview_revision, expires_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            _hash_token(token),
            operation,
            details_digest,
            preview_revision,
            (now + TOKEN_TTL).isoformat(timespec="seconds"),
        ),
    )
    return token


def _row(conn: sqlite3.Connection, token: str, operation: str, details_digest: str) -> sqlite3.Row:
    row = conn.execute(
        """
        SELECT operation, details_digest, preview_revision, expires_at, used_at, result_json
        FROM pending_confirmations WHERE token_hash = ?
        """,
        (_hash_token(token),),
    ).fetchone()
    if row is None or row["operation"] != operation or row["details_digest"] != details_digest:
        raise _invalid()
    return row


def stored_outcome(
    conn: sqlite3.Connection, *, token: str, operation: str, details_digest: str
) -> dict[str, Any] | None:
    """Read-only check: the recorded outcome if this token was already confirmed, else None."""
    row = _row(conn, token, operation, details_digest)
    if row["used_at"] is None:
        return None
    if row["result_json"] is None:
        raise _invalid()
    result: dict[str, Any] = json.loads(row["result_json"])
    return result


def consume(
    conn: sqlite3.Connection,
    *,
    token: str,
    operation: str,
    details_digest: str,
    current_revision: int,
    now: datetime,
) -> dict[str, Any] | None:
    """Mark a token used, or return its recorded outcome if it was already used.

    Call inside the same write transaction as the change it authorises. Returns None on first
    use, after which the caller writes and then calls `record_outcome`. Returns the stored
    outcome on a replay, in which case the caller must not write.
    """
    row = _row(conn, token, operation, details_digest)
    if row["used_at"] is not None:
        if row["result_json"] is None:
            raise _invalid()
        result: dict[str, Any] = json.loads(row["result_json"])
        return result
    if row["preview_revision"] != current_revision:
        # The booking changed after the caller reviewed it. Ask them to review again.
        raise ApiError(
            "invalid_confirmation",
            "This booking changed after you reviewed it. Review the change again.",
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
    return None


def record_outcome(conn: sqlite3.Connection, *, token: str, outcome: dict[str, Any]) -> None:
    """Store what a confirmed token did, so a later retry can be answered without writing."""
    conn.execute(
        "UPDATE pending_confirmations SET result_json = ? WHERE token_hash = ?",
        (json.dumps(outcome, sort_keys=True), _hash_token(token)),
    )
