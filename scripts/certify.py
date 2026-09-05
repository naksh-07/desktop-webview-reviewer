#!/usr/bin/env python3
"""
Multi-Framework Live Certification CLI (Phase 19).
Executes live certification across QtWebEngine (Anki Maths), Electron, WebView2,
Generic Chromium / CEF, and WebKit.
Outputs formatted reports and saves machine-readable `certification_matrix.json`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.certification import RealAppCertifier, CertificationMatrix


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="desktop-reviewer certify",
        description="Run multi-framework live adversarial certification against real desktop applications."
    )
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    parser.add_argument("--output-dir", type=str, default=None, help="Directory to save certification artifacts")
    parser.add_argument("--framework", type=str, default=None, help="Certify only specific framework (e.g. qtwebengine, electron, webview2)")

    args = parser.parse_args(argv)

    out_dir = Path(args.output_dir).resolve() if args.output_dir else None
    certifier = RealAppCertifier(output_dir=out_dir)

    async def run():
        if args.framework:
            fw = args.framework.lower()
            if fw in ("qt", "qtwebengine"):
                entry = await certifier.certify_qtwebengine()
            elif fw in ("electron",):
                entry = await certifier.certify_electron()
            elif fw in ("webview2", "edge"):
                entry = await certifier.certify_webview2()
            elif fw in ("chromium", "cef"):
                entry = certifier.certify_generic_chromium_cef()
            elif fw in ("webkit",):
                entry = certifier.certify_webkit()
            else:
                print(f"Unknown framework: {fw}", file=sys.stderr)
                return 1

            if args.json:
                print(json.dumps(entry.to_dict(), indent=2))
            else:
                _print_entry(entry)
            return 0 if entry.verdict in ("PASS", "UNVERIFIED") else 1

        matrix = await certifier.run_full_certification()

        if args.json:
            print(matrix.to_json())
        else:
            _print_matrix(matrix)

        return 0 if matrix.overall_verdict == "PASS" else 1

    return asyncio.run(run())


def _print_entry(entry):
    print("+-------------------------------------------------------------+")
    print(f"| Framework:   {entry.framework:<46} |")
    print(f"| Engine:      {entry.engine:<46} |")
    print(f"| Fixture:     {entry.runtime_fixture[:46]:<46} |")
    print(f"| Capability:  {entry.capability_state:<46} |")
    print(f"| Physical:    {entry.physical_reality_result:<46} |")
    print(f"| Assertion:   {entry.assertion_result:<46} |")
    print(f"| Evidence:    {entry.evidence_result:<46} |")
    print(f"| Verdict:     {entry.verdict:<46} |")
    print(f"| Duration:    {entry.duration_ms:.1f}ms{' ':<40}|")
    print("+-------------------------------------------------------------+")
    if entry.limitations:
        print("  Limitations / Notes:")
        for lim in entry.limitations:
            print(f"   - {lim}")


def _print_matrix(matrix: CertificationMatrix):
    print("===============================================================")
    print("   DESKTOP WEBVIEW REVIEWER 2.0 -- LIVE CERTIFICATION MATRIX   ")
    print("===============================================================")
    print(f"Generated At: {matrix.generated_at}")
    print(f"Host OS:      {matrix.host_os} ({matrix.host_arch})")
    print(f"Python:       {matrix.python_version}")
    print(f"Verdict:      {matrix.overall_verdict}")
    print("---------------------------------------------------------------")
    header = f"{'Engine':<14} | {'Capability State':<18} | {'Physical':<8} | {'Evidence':<8} | {'Verdict':<8}"
    print(header)
    print("-" * len(header))
    for e in matrix.entries:
        print(f"{e.engine:<14} | {e.capability_state:<18} | {e.physical_reality_result:<8} | {e.evidence_result:<8} | {e.verdict:<8}")
    print("---------------------------------------------------------------")
    print(f"Total: {len(matrix.entries)} | Runtime Verified: {matrix.runtime_verified_count} | Protocol Verified: {matrix.protocol_verified_count} | Unavailable: {matrix.unavailable_count}")
    print("===============================================================")


if __name__ == "__main__":
    sys.exit(main())
