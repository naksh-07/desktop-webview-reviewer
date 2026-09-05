#!/usr/bin/env python3
"""
CLI utility for Recovery Engine & Circuit Breaker (Architecture H / Phase 16).
Usage:
    python -m scripts.recovery_cli status [--json]
    python -m scripts.recovery_cli candidates <FAILURE_CATEGORY> [--json]
"""

from __future__ import annotations
import argparse
import json
import os
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.diagnostics import FailureCategory
from runtime.recovery_engine import CircuitBreaker, RecoveryPolicy, RecoveryAction


def main() -> int:
    parser = argparse.ArgumentParser(description="Recovery Engine & Circuit Breaker CLI")
    subparsers = parser.add_subparsers(dest="subcommand", help="Recovery command")

    # 1. status
    status_p = subparsers.add_parser("status", help="Inspect circuit breaker status.")
    status_p.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    # 2. candidates
    cand_p = subparsers.add_parser("candidates", help="List recovery candidates for a failure category.")
    cand_p.add_argument("category", choices=[c.value for c in FailureCategory], help="Failure category.")
    cand_p.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    args = parser.parse_args()

    if args.subcommand == "status":
        cb = CircuitBreaker()
        data = cb.to_dict()
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print("=== Circuit Breaker Status ===")
            print(f"State:                      {data['state']}")
            print(f"Consecutive Failures:       {data['failure_count']} / {data['max_consecutive_failures']}")
            print(f"Successful Recoveries:      {data['recovery_count']}")
            print(f"Block Reason:               {data['block_reason'] or 'None (Recovery Allowed)'}")
        return 0

    elif args.subcommand == "candidates":
        cat_enum = FailureCategory(args.category)
        candidates = RecoveryPolicy.get_recovery_candidates(cat_enum)
        max_attempts = RecoveryPolicy.get_max_attempts(cat_enum)
        data = {
            "failure_category": cat_enum.value,
            "is_recoverable": cat_enum.is_recoverable,
            "max_attempts": max_attempts,
            "recovery_candidates": [c.value for c in candidates],
        }
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"=== Recovery Policy for {cat_enum.value} ===")
            print(f"Recoverable:         {cat_enum.is_recoverable}")
            print(f"Max Attempts:        {max_attempts}")
            print(f"Allowed Actions:     {', '.join(data['recovery_candidates']) or 'None'}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
