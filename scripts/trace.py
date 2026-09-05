#!/usr/bin/env python3
"""
CLI utility to query and inspect Desktop Trace timelines and event correlation.
Usage:
    python -m scripts.trace [--session-id SESSION_ID] [--action-id ACTION_ID] [--limit 50] [--json]
"""

from __future__ import annotations
import argparse
import json
import os
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.trace_engine import DesktopTraceEngine


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect desktop trace events.")
    parser.add_argument("--session-id", type=str, default="default", help="Session ID.")
    parser.add_argument("--action-id", type=str, default=None, help="Filter by Action ID.")
    parser.add_argument("--limit", type=int, default=50, help="Maximum events to display.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    engine = DesktopTraceEngine(session_id=args.session_id)
    events = engine.query(action_id=args.action_id, limit=args.limit)

    if args.json:
        print(json.dumps([e.to_dict() for e in events], indent=2))
    else:
        print(f"=== Desktop Trace Timeline (Session: {args.session_id}, Events: {len(events)}) ===")
        for e in events:
            time_str = f"{e.timestamp:.3f}"
            print(f"[{time_str}] #{e.sequence_monotonic} {e.event_type.value:<20} plane={e.plane.value:<10} status={e.status} {e.target_reference or ''}")
            if e.details:
                print(f"       details: {e.details}")


if __name__ == "__main__":
    main()
