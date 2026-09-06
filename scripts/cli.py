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

from typing import Optional, List


def main(argv: Optional[List[str]] = None) -> int:
    if argv is not None:
        sys.argv = ["desktop-reviewer"] + list(argv)
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "harness":
            sys.argv.pop(1)
            from scripts.harness import main as harness_main
            return harness_main()
        elif cmd == "mission":
            sys.argv.pop(1)
            from scripts.mission_cli import main as mission_main
            return mission_main()
        elif cmd == "specialists":
            sys.argv.pop(1)
            from scripts.specialists_cli import main as specialists_main
            return specialists_main()
        elif cmd == "recovery":
            sys.argv.pop(1)
            from scripts.recovery_cli import main as recovery_main
            return recovery_main()
        elif cmd == "diagnostics":
            sys.argv.pop(1)
            from scripts.diagnostics import main as diagnostics_main
            diagnostics_main()
            return 0
        elif cmd == "doctor":
            sys.argv.pop(1)
            from scripts.doctor import main as doctor_main
            return doctor_main()
        elif cmd == "inspect":
            sys.argv.pop(1)
            from scripts.desktop_inspect import main as inspect_main
            inspect_main()
            return 0
        elif cmd == "screenshot":
            sys.argv.pop(1)
            from scripts.screenshot import main as screenshot_main
            screenshot_main()
            return 0
        elif cmd == "trace":
            sys.argv.pop(1)
            from scripts.trace import main as trace_main
            trace_main()
            return 0
        elif cmd in ("certify", "certification"):
            sys.argv.pop(1)
            from scripts.certify import main as certify_main
            return certify_main()
        elif cmd in ("security-audit", "audit"):
            sys.argv.pop(1)
            from scripts.security_audit import main as audit_main
            audit_main()
            return 0
        elif cmd in ("release-validate", "validate-release", "release"):
            sys.argv.pop(1)
            from scripts.release_validator import main as release_main
            return release_main()

    # Generic help
    print("Desktop WebView Reviewer 2.0 CLI")
    print("Usage: desktop-reviewer <command> [options]")
    print()
    print("Commands:")
    print("  mission          Autonomous review missions (validate, run, status, cancel)")
    print("  specialists      Invoke and inspect subordinate specialist subagents (Explorer, Tester, etc.)")
    print("  diagnostics      Unified diagnostic aggregator, failure correlation, and forensics")
    print("  recovery         Inspect circuit breaker status, recovery policy, and reliability")
    print("  certify          Multi-framework live adversarial certification matrix")
    print("  security-audit   Full 6-point repository and runtime security audit")
    print("  release-validate Deterministic 8-gate production release validation pipeline")
    print("  harness          Manage application-side Reviewer Test Harness (init, inspect, remove, validate-release)")
    print("  doctor           Run diagnostic environment check")
    print("  inspect          Inspect desktop window hierarchy and reality reconciliation")
    print("  screenshot       Capture authoritative desktop or window screenshot")
    print("  trace            Inspect chronological desktop trace events")
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
