"""Payload-free completed SDK request counts for local review operations."""

from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
import logging
from typing import Any, Iterator


class RequestMetrics:
    def __init__(self) -> None:
        self._current: ContextVar[Counter[str] | None] = ContextVar(
            "review_request_counts", default=None
        )

    def attach(self, client: Any, service: str) -> None:
        previous = client.on_request_completed

        def completed(method: str, endpoint: str, payload: Any,
                      status: int, body: Any) -> None:
            counts = self._current.get()
            if counts is not None:
                counts[service] += 1
            if previous is not None:
                previous(method, endpoint, payload, status, body)

        client.on_request_completed = completed

    @contextmanager
    def operation(self, name: str) -> Iterator[Counter[str]]:
        counts: Counter[str] = Counter()
        token = self._current.set(counts)
        try:
            yield counts
        finally:
            self._current.reset(token)
            logging.info("Review requests operation=%s completed=%s total=%s",
                         name, dict(counts), sum(counts.values()))
