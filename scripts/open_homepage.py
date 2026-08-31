#!/usr/bin/env python3
"""Start the project dashboard if needed, then open it in the default browser."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Optional, Sequence
from urllib.error import URLError
from urllib.request import urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DASHBOARD_URL = "http://127.0.0.1:8750"
HEALTH_URL = f"{DASHBOARD_URL}/api/state"


def dashboard_is_running(timeout: float = 0.5) -> bool:
    """Return whether the expected dashboard is responding on its local port."""
    try:
        with urlopen(HEALTH_URL, timeout=timeout) as response:
            payload = json.load(response)
        return (
            response.status == 200
            and isinstance(payload.get("workflows"), list)
            and isinstance(payload.get("runs"), list)
        )
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return False


def start_dashboard() -> subprocess.Popen[bytes]:
    """Launch the dashboard independently of the short-lived VS Code task."""
    log_dir = PROJECT_ROOT / "logs"
    log_dir.mkdir(exist_ok=True)
    log_path = log_dir / "project_dashboard.auto.log"

    kwargs: dict[str, object] = {
        "cwd": PROJECT_ROOT,
        "stdin": subprocess.DEVNULL,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        )
    else:
        kwargs["start_new_session"] = True

    with log_path.open("ab") as log_file:
        return subprocess.Popen(
            [sys.executable, str(PROJECT_ROOT / "scripts" / "project_dashboard.py")],
            stdout=log_file,
            stderr=subprocess.STDOUT,
            **kwargs,
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Start and verify the dashboard without opening a browser tab.",
    )
    parser.add_argument("--timeout", type=float, default=8.0)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    process: Optional[subprocess.Popen[bytes]] = None

    if not dashboard_is_running():
        process = start_dashboard()
        deadline = time.monotonic() + args.timeout
        while time.monotonic() < deadline:
            if dashboard_is_running():
                break
            if process.poll() is not None:
                print(
                    "Project dashboard exited during startup. See "
                    "logs/project_dashboard.auto.log.",
                    file=sys.stderr,
                )
                return 1
            time.sleep(0.1)
        else:
            print(
                f"Project dashboard did not become ready within {args.timeout:g} seconds. "
                "See logs/project_dashboard.auto.log.",
                file=sys.stderr,
            )
            return 1

    if not args.no_browser:
        webbrowser.open(DASHBOARD_URL)
    print(f"Project homepage ready: {DASHBOARD_URL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
