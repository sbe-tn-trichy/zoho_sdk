#!/usr/bin/env python3
"""Import one Polycab RSO PDF into Zoho Books as a sales order."""

import argparse
import json
import sys
from pathlib import Path

try:
    from . import _bootstrap  # noqa: F401
except ImportError:  # Direct script execution.
    import _bootstrap  # type: ignore[no-redef]  # noqa: F401

from workflows import get_books_client, import_polycab_rso_pdf
from workflows.core.config import Config


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdf_path", help="Path to a machine-readable Polycab RSO PDF")
    parser.add_argument("--customer-id", default=Config.RSO_CUSTOMER_ID)
    parser.add_argument("--location-id", default=Config.EXPECTED_LOCATION_ID)
    args = parser.parse_args()

    result = import_polycab_rso_pdf(
        get_books_client(),
        args.pdf_path,
        customer_id=args.customer_id,
        location_id=args.location_id,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
