#!/usr/bin/env python3
"""Download Books Sales Persons and Beat custom modules; never writes to Books."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
try:
    from . import _bootstrap  # noqa: F401
except ImportError:
    import _bootstrap  # noqa: F401
from workflows.core.auth import get_books_client
from workflows.books_custom_module_store import download_books_custom_modules


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, default=Path('output/books_custom_modules/modules.sqlite3'))
    args = parser.parse_args()
    print(json.dumps(download_books_custom_modules(get_books_client(), database=args.database)))


if __name__ == '__main__':
    main()
