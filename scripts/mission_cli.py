#!/usr/bin/env python3
"""
Developer CLI for Autonomous Review Missions (Phase 17-18).
Exposes exactly four minimal developer operations:
    desktop-reviewer mission validate <mission.json>
    desktop-reviewer mission run <mission.json>
    desktop-reviewer mission status <mission_id>
    desktop-reviewer mission cancel <mission_id>
Uses the authoritative ReviewMissionOrchestrator runtime without code duplication.
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Optional, List

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.mission_models import ReviewMission
from runtime.mission_admission import MissionAdmissionGate
from runtime.mission_orchestrator import ReviewMissionOrchestrator
from runtime.antigravity_adapter import AntigravityReviewerAdapter

# Shared orchestrator instance for CLI invocation
_cli_adapter = AntigravityReviewerAdapter()


def cmd_validate(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"Error: Mission file '{args.file}' not found.", file=sys.stderr)
        return 1

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mission = ReviewMission.from_dict(data)
    except Exception as e:
        print(f"Error parsing mission JSON: {e}", file=sys.stderr)
        return 1

    gate = MissionAdmissionGate()
    result = gate.validate(mission)
    if result.is_admitted:
        print(f"PASS: Mission '{mission.mission_id}' is valid and ready for admission.")
        print(f"  Objective: {mission.objective}")
        print(f"  Declared Scope: {mission.declared_scope}")
        print(f"  Criteria Count: {len(mission.acceptance_criteria)}")
        digest = mission._authority_digest[:16] + "..." if mission._authority_digest else "None"
        print(f"  Authority Digest: {digest}")
        return 0
    else:
        print(f"REJECTED: Mission '{mission.mission_id}' failed admission gate:", file=sys.stderr)
        for r in result.rejections:
            print(f"  - {r}", file=sys.stderr)
        return 2


def cmd_run(args: argparse.Namespace) -> int:
    path = Path(args.file)
    if not path.exists():
        print(f"Error: Mission file '{args.file}' not found.", file=sys.stderr)
        return 1

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        mission = ReviewMission.from_dict(data)
    except Exception as e:
        print(f"Error parsing mission JSON: {e}", file=sys.stderr)
        return 1

    print(f"Submitting and executing mission '{mission.mission_id}'...")
    admission = _cli_adapter.submit_mission(mission.to_dict())
    if not admission.is_admitted:
        print(f"Admission rejected:", file=sys.stderr)
        for r in admission.rejections:
            print(f"  - {r}", file=sys.stderr)
        return 2

    result = asyncio.run(_cli_adapter.execute_mission(mission.mission_id))
    print(f"\nMission Finished: {result.final_status.value}")
    print(f"Technical Verdict: {result.technical_verdict}")
    print(f"Completed Steps: {len(result.completed_steps)}")
    print(f"Failed Steps: {len(result.failed_steps)}")
    print(f"Duration: {result.duration_ms:.1f}ms")
    if result.evidence_refs:
        print(f"Evidence Artifacts: {', '.join(result.evidence_refs)}")
    if result.limitations:
        print("Limitations:")
        for lim in result.limitations:
            print(f"  - {lim}")

    return 0 if result.technical_verdict == "PASS" else 1


def cmd_status(args: argparse.Namespace) -> int:
    status = _cli_adapter.get_mission_status(args.mission_id)
    if not status:
        print(f"Mission '{args.mission_id}' not found.", file=sys.stderr)
        return 1
    print(json.dumps(status, indent=2))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    reason = args.reason or "Cancelled by CLI developer command"
    success = _cli_adapter.cancel_mission(args.mission_id, reason=reason)
    if success:
        print(f"Mission '{args.mission_id}' marked for cancellation.")
        return 0
    else:
        print(f"Could not cancel mission '{args.mission_id}' (not active or not found).", file=sys.stderr)
        return 1


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="desktop-reviewer mission",
        description="Autonomous Review Mission CLI (Phases 17-18)",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Mission subcommands")

    # validate
    val_parser = subparsers.add_parser("validate", help="Validate a mission JSON file against the admission gate")
    val_parser.add_argument("file", help="Path to mission JSON file")

    # run
    run_parser = subparsers.add_parser("run", help="Submit and run a review mission")
    run_parser.add_argument("file", help="Path to mission JSON file")

    # status
    stat_parser = subparsers.add_parser("status", help="Query mission execution status")
    stat_parser.add_argument("mission_id", help="Target mission ID")

    # cancel
    canc_parser = subparsers.add_parser("cancel", help="Cancel an active mission")
    canc_parser.add_argument("mission_id", help="Target mission ID")
    canc_parser.add_argument("--reason", default=None, help="Cancellation reason")

    args = parser.parse_args(argv)
    if not args.subcommand:
        parser.print_help()
        return 1

    if args.subcommand == "validate":
        return cmd_validate(args)
    elif args.subcommand == "run":
        return cmd_run(args)
    elif args.subcommand == "status":
        return cmd_status(args)
    elif args.subcommand == "cancel":
        return cmd_cancel(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
