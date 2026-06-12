"""Command-line entrypoint for mono-control."""

import argparse
from importlib.metadata import version
from pathlib import Path

from mono_control.sandbox import require_container

WORKSPACES = Path("/workspaces")

# Directories mono-control governs, bind-mounted as siblings in the container.
MANAGED_DIRS = ("mono-config", "mono-repos")


def _status() -> int:
    """Report which managed workspace directories are visible."""
    for name in MANAGED_DIRS:
        path = WORKSPACES / name
        mark = "ok " if path.is_dir() else "missing"
        print(f"  [{mark}] {path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    require_container()

    parser = argparse.ArgumentParser(
        prog="mono-control",
        description="Repo state manager for the fiemono workspace.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('mono-control')}",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "status",
        help="Report which managed workspace directories are visible.",
    )

    args = parser.parse_args(argv)

    if args.command == "status":
        return _status()
    return 0
