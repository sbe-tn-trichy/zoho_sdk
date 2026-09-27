"""Shared atomic JSON writing and checkpointing utility."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Callable, Mapping, Optional


def write_atomic_json(
    path: Path | str,
    payload: Any,
    *,
    indent: int = 2,
    default: Optional[Callable[[Any], Any]] = str,
    max_retries: int = 5,
    retry_delay: float = 0.1,
    sort_keys: bool = False,
) -> None:
    """Safely write JSON payload to disk via a temporary file and atomic replace.

    Supports configurable retry behavior for Windows file locking and optional custom serializers.
    """
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    text = json.dumps(payload, indent=indent, default=default, sort_keys=sort_keys) + "\n"
    temporary.write_text(text, encoding="utf-8")

    for attempt in range(max(1, max_retries)):
        try:
            os.replace(temporary, target)
            break
        except PermissionError:
            if attempt >= max_retries - 1:
                raise
            time.sleep(retry_delay * (attempt + 1))
