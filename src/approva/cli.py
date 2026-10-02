"""Command-line entry point for Approva."""

from __future__ import annotations

import argparse
import sys

from approva import db


def main() -> int:
    """Parse and run the supported command-line operation."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="approva")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="create and populate the demo database")
    args = parser.parse_args()
    if args.command == "seed":
        db.seed_from_yaml()
        print("Seeded Approva employees and vendors.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())