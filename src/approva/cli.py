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
    inbox_parser = commands.add_parser("inbox", help="list requests awaiting your approval")
    inbox_parser.add_argument("--as", dest="acting_as", default="E002")
    approve_parser = commands.add_parser("approve", help="approve or reject a request")
    approve_parser.add_argument("request_id")
    approve_parser.add_argument("--as", dest="acting_as", default="E002")
    approve_parser.add_argument("--reject", action="store_true")
    approve_parser.add_argument("--comment", default=None)
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
    elif args.command == "inbox":
        with db.connection() as conn:
            rows = conn.execute(
                "SELECT r.id,r.requester_id,r.decision_json,e.manager_id,e.role "
                "FROM requests r JOIN employees e ON e.id=r.requester_id WHERE r.status='AWAITING_APPROVAL'"
            ).fetchall()
        actor = _employee(args.acting_as)
        visible = []
        for row in rows:
            decision = __import__("json").loads(row["decision_json"] or "{}")
            required = decision.get("required_roles", [])
            actor_role = "manager" if row["manager_id"] == args.acting_as and actor.get("role") == "manager" else actor.get("role")
            if actor_role in required:
                visible.append(row["id"])
        console = Console(markup=False)
        console.print("Approval inbox: " + (", ".join(visible) if visible else "empty"))
    elif args.command == "approve":
        import json
        from approva.approvals import submit

        request = db.get_request(args.request_id)
        actor = _employee(args.acting_as)
        if request is None:
            raise SystemExit(f"Request not found: {args.request_id}")
        decision = json.loads(request.get("decision_json") or "{}")
        with db.connection() as conn:
            requester = conn.execute("SELECT manager_id FROM employees WHERE id=?", (request["requester_id"],)).fetchone()
        role = "manager" if requester and requester["manager_id"] == args.acting_as else actor.get("role")
        if role not in decision.get("required_roles", []):
            raise SystemExit(f"{args.acting_as} has no required role for {args.request_id}")
        verdict = "reject" if args.reject else "approve"
        console = Console(markup=False)
        for event in submit(args.request_id, args.acting_as, role, verdict, args.comment):
            console.print(f"[{event.agent}] {event.status}: {event.summary}")
    return 0


def _employee(employee_id: str) -> dict:
    """Return an employee row for CLI approval-role selection."""
    with db.connection() as conn:
        row = conn.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    return dict(row) if row else {}


if __name__ == "__main__":
    raise SystemExit(main())