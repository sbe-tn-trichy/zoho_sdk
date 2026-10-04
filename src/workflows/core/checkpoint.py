"""Shared atomic JSON writing and checkpointing utility."""

from __future__ import annotations

import json
import os
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, TextIO


def write_atomic_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int | None = 2,
    default: Optional[Callable[[Any], Any]] = str,
    max_retries: int = 5,
    retry_delay: float = 0.1,
    sort_keys: bool = False,
    ensure_ascii: bool = True,
) -> None:
    """Safely write JSON payload to disk via a temporary file and atomic replace.

    Each writer stages its own file; concurrent writes use last-replacement-wins
    semantics. Supports retries for Windows file locking and custom serializers.
    """
    text = json.dumps(payload, indent=indent, default=default, sort_keys=sort_keys,
                      ensure_ascii=ensure_ascii) + "\n"
    with atomic_text_writer(path, max_retries=max_retries, retry_delay=retry_delay) as staged:
        staged.write(text)


@contextmanager
def atomic_text_writer(
    path: Path | str, *, encoding: str = "utf-8", newline: str | None = None,
    max_retries: int = 5, retry_delay: float = 0.1,
) -> Iterator[TextIO]:
    """Stage a text/CSV file uniquely, replacing the target only on success."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding=encoding, newline=newline, dir=target.parent,
            prefix=target.name + ".", suffix=".tmp", delete=False,
        ) as staged:
            temporary = Path(staged.name)
            yield staged

        attempts = max(1, max_retries)
        for attempt in range(attempts):
            try:
                os.replace(temporary, target)
                break
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(retry_delay * (attempt + 1))
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
