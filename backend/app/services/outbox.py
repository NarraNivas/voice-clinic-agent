"""Delivers queued staff handoffs to the CRM sandbox, with bounded retries.

The worker takes a clock argument, so a test can step time forward instead of sleeping.

Delivery rules:
- A handoff is only marked delivered after the CRM answers 200 or 201 with a case reference.
- Network errors, timeouts, 429, and 5xx are retried with exponential backoff, up to
  MAX_ATTEMPTS. After that the handoff is marked failed.
- Other 4xx answers are not retried. A 409 means the CRM already holds different content under
  the same request id, which retrying cannot fix.
- Before each send, the row is pushed out by a short lease. A second worker running at the same
  moment skips it, and a crashed worker's row becomes due again once the lease ends.
"""

import json
import sqlite3
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Protocol

from app.repositories import outbox as repo

MAX_ATTEMPTS = 5
LEASE = timedelta(seconds=60)
BASE_BACKOFF = timedelta(seconds=30)
MAX_BACKOFF = timedelta(minutes=15)
REQUEST_TIMEOUT_SECONDS = 5.0


def backoff_after(attempts: int) -> timedelta:
    """Delay before the next try, after `attempts` failed tries: 30s, 60s, 120s, ... capped."""
    return min(BASE_BACKOFF * (2 ** max(attempts - 1, 0)), MAX_BACKOFF)


class CrmUnavailable(Exception):
    """The CRM could not be reached, or the connection failed before a status came back."""


@dataclass(frozen=True)
class CrmReply:
    status: int
    case_ref: str | None


class CrmClient(Protocol):
    def put_case(self, request_id: str, payload: dict[str, Any]) -> CrmReply: ...


class HttpCrmClient:
    """Sends handoffs to a CRM over HTTP with the standard library. No extra dependency."""

    def __init__(self, base_url: str, timeout: float = REQUEST_TIMEOUT_SECONDS) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def put_case(self, request_id: str, payload: dict[str, Any]) -> CrmReply:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/cases/{request_id}",
            data=body,
            method="PUT",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                reply = json.loads(response.read() or b"{}")
                return CrmReply(status=response.status, case_ref=reply.get("case_ref"))
        except urllib.error.HTTPError as error:
            return CrmReply(status=error.code, case_ref=None)
        except (TimeoutError, urllib.error.URLError, ConnectionError, OSError) as error:
            raise CrmUnavailable(type(error).__name__) from error


@dataclass(frozen=True)
class Delivery:
    request_id: str
    outcome: str  # delivered | retry | failed
    attempts: int
    error: str | None = None


def deliver_due(
    conn: sqlite3.Connection,
    client: CrmClient,
    *,
    now: datetime,
    limit: int = 50,
) -> list[Delivery]:
    """Try every queued handoff that is due at `now`. Returns what happened to each one."""
    results: list[Delivery] = []
    for row in repo.due(conn, now, limit):
        repo.claim(conn, row.request_id, now + LEASE)
        attempts = row.attempts + 1
        try:
            reply: CrmReply | None = client.put_case(row.request_id, row.payload)
            error = None
        except CrmUnavailable as failure:
            reply, error = None, f"unreachable: {failure}"

        if reply is not None and reply.status in (200, 201) and reply.case_ref:
            repo.mark_delivered(
                conn, row.request_id, case_ref=reply.case_ref, attempts=attempts, now=now
            )
            results.append(Delivery(row.request_id, "delivered", attempts))
            continue

        if reply is not None:
            error = f"http_{reply.status}"
        retryable = reply is None or reply.status == 429 or reply.status >= 500
        if retryable and attempts < MAX_ATTEMPTS:
            repo.mark_retry(
                conn,
                row.request_id,
                attempts=attempts,
                next_attempt_at=now + backoff_after(attempts),
                error=error or "unknown",
            )
            results.append(Delivery(row.request_id, "retry", attempts, error))
        else:
            repo.mark_failed(conn, row.request_id, attempts=attempts, error=error or "unknown")
            results.append(Delivery(row.request_id, "failed", attempts, error))
    return results
