"""Payload-free completed SDK request counts for local review operations."""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import logging
from threading import Lock
from time import monotonic
from typing import Any, Iterator, Mapping


@dataclass
class HttpAttemptMetrics:
    """Physical attempts, including retries and transport failures; no record IDs."""

    requests: Counter[str] = field(default_factory=Counter)
    http_seconds: Counter[str] = field(default_factory=Counter)
    statuses: Counter[str] = field(default_factory=Counter)
    _lock: Lock = field(default_factory=Lock, repr=False)

    @staticmethod
    def resource(endpoint: str) -> str:
        parts = endpoint.split("?", 1)[0].strip("/").split("/")
        # Creator paths include an owner and app; only retain the resource kind.
        if parts[0] in {"data", "meta"}:
            kind = next((part for part in parts[3:5]
                         if part in {"report", "form", "forms", "reports", "applications"}), "root")
            return f"creator {kind}"
        return f"{parts[0] or 'root'} {'detail' if len(parts) > 1 else 'list'}"

    def on_attempt(self, service: str, method: str, endpoint: str,
                   elapsed: float, status: int | None) -> None:
        resource = "workbook" if service == "sheet" else self.resource(endpoint)
        key = f"{service}/{resource}"
        with self._lock:
            self.requests[key] += 1
            self.http_seconds[key] += elapsed
            self.statuses[f"{service}/{status if status is not None else 'error'}"] += 1


class OperationCounts(Counter[str]):
    """Compatible completed-call Counter with physical-attempt and cache evidence."""

    def __init__(self, counts: Mapping[str, int] | None = None) -> None:
        super().__init__(counts)
        self.http = HttpAttemptMetrics()
        self.cache_hits: Counter[str] = Counter()
        self.started = monotonic()
        self.elapsed_seconds = 0.0
        self.lock = Lock()


class RequestMetrics:
    def __init__(self) -> None:
        self._current: ContextVar[OperationCounts | None] = ContextVar(
            "review_request_counts", default=None
        )

    def attach(self, client: Any, service: str) -> None:
        previous = client.on_request_completed

        def completed(method: str, endpoint: str, payload: Any,
                      status: int, body: Any) -> None:
            counts = self._current.get()
            if counts is not None:
                with counts.lock:
                    counts[service] += 1
            if previous is not None:
                previous(method, endpoint, payload, status, body)

        client.on_request_completed = completed
        previous_attempt = getattr(client, "on_http_attempt", None)

        def attempted(actual_service: str, method: str, endpoint: str,
                      elapsed: float, status: int | None) -> None:
            counts = self._current.get()
            if counts is not None:
                counts.http.on_attempt(service, method, endpoint, elapsed, status)
            if previous_attempt is not None:
                previous_attempt(actual_service, method, endpoint, elapsed, status)

        client.on_http_attempt = attempted

    def cache_hit(self, name: str, count: int = 1) -> None:
        counts = self._current.get()
        if counts is not None:
            with counts.lock:
                counts.cache_hits[name] += count

    @contextmanager
    def operation(self, name: str) -> Iterator[OperationCounts]:
        counts = OperationCounts()
        token = self._current.set(counts)
        try:
            yield counts
        finally:
            self._current.reset(token)
            counts.elapsed_seconds = monotonic() - counts.started
            logging.info("Review requests operation=%s completed=%s total=%s "
                         "attempts=%s http_seconds=%s statuses=%s elapsed=%.3fs cache_hits=%s",
                         name, dict(counts), sum(counts.values()),
                         dict(counts.http.requests), dict(counts.http.http_seconds),
                         dict(counts.http.statuses), counts.elapsed_seconds, dict(counts.cache_hits))
