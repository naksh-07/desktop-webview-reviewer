#!/usr/bin/env python3
"""
Top-level CLI dispatcher for `desktop-reviewer` (Architecture H).
Usage:
    desktop-reviewer harness <subcommand> [...]
    desktop-reviewer doctor
    desktop-reviewer inspect
    desktop-reviewer trace
"""

from __future__ import annotations
import os
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "harness":
        # Forward directly to harness CLI
        sys.argv.pop(1)
        from scripts.harness import main as harness_main
        return harness_main()

    # Generic help
    print("Desktop WebView Reviewer 2.0 CLI")
    print("Usage: desktop-reviewer <command> [options]")
    print()
    print("Commands:")
    print("  harness          Manage application-side Reviewer Test Harness (init, inspect, remove, validate-release)")
    print("  doctor           Run diagnostic environment check")
    print("  inspect          Inspect desktop window hierarchy and reality reconciliation")
    print("  screenshot       Capture authoritative desktop or window screenshot")
    print("  trace            Inspect chronological desktop trace events")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
