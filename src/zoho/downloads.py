"""Internal helpers for safely writing API download responses to disk."""

import os
from typing import Any


def write_response_to_file(
    response: Any,
    destination: str,
    chunk_size: int = 8192,
) -> str:
    """Write bytes or a streaming HTTP response to ``destination`` and close it."""
    close = getattr(response, "close", None)
    try:
        is_binary = isinstance(response, (bytes, bytearray))
        iter_content = getattr(response, "iter_content", None)
        content = getattr(response, "content", None)
        if not is_binary and not callable(iter_content) and not isinstance(content, (bytes, bytearray)):
            raise TypeError("Download response must be bytes or provide binary content.")

        parent = os.path.dirname(destination)
        if parent:
            os.makedirs(parent, exist_ok=True)

        with open(destination, "wb") as output:
            if is_binary:
                output.write(response)
                return destination

            if callable(iter_content):
                for chunk in iter_content(chunk_size=chunk_size):
                    if chunk:
                        output.write(chunk)
                return destination

            output.write(content)
            return destination
    finally:
        if callable(close):
            close()
