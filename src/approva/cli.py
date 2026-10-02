"""Command-line entry point for Approva."""

from __future__ import annotations

import argparse
import sys

from approva import db
from rich.console import Console


def main() -> int:
    """Parse and run the supported command-line operation."""
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="approva")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="create and populate the demo database")
    run_parser = commands.add_parser("run", help="process a new employee request")
    run_parser.add_argument("request_text")
    run_parser.add_argument("--as", dest="acting_as", default="E001")
    args = parser.parse_args()
    if args.command == "seed":
        db.seed_from_yaml()
        print("Seeded Approva employees and vendors.")
    elif args.command == "run":
        from approva.orchestrator import create_request, process_request

        request_id = create_request(args.acting_as, args.request_text)
        console = Console(markup=False)
        for event in process_request(request_id):
            latency = f" ({event.latency_ms} ms)" if event.latency_ms is not None else ""
            console.print(f"[{event.agent}] {event.status}: {event.summary}{latency}")
        request = db.get_request(request_id)
        decision = request.get("decision_json") if request else None
        console.print(f"Request {request_id}: {request['status'] if request else 'unknown'}")
        console.print(f"Decision: {decision or 'MANUAL_REVIEW'}")
        console.print("Next: review the request in Approvals." if request and request["status"] == "AWAITING_APPROVAL" else "Next: inspect request status.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())