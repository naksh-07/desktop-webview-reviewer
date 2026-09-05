#!/usr/bin/env python3
"""
CLI utility to capture real desktop or window screenshots.
Usage:
    python -m scripts.screenshot [--hwnd HWND] [--scope {window,desktop}] [--out PATH]
"""

from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.native_supervisor import NativeSupervisor


def main() -> None:
    parser = argparse.ArgumentParser(description="Capture desktop or window screenshot.")
    parser.add_argument("--hwnd", type=lambda x: int(x, 0), default=None, help="Target window HWND (decimal or 0x hex).")
    parser.add_argument("--scope", choices=["window", "desktop"], default="desktop", help="Capture scope.")
    parser.add_argument("--out", type=str, default="screenshot.png", help="Output PNG file path.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    supervisor = NativeSupervisor()
    png_bytes = None

    if args.scope == "window" and args.hwnd:
        res = supervisor.capture_window_screenshot(args.hwnd)
        png_bytes = res[1] if isinstance(res, tuple) and res[0] else (res if isinstance(res, bytes) else None)
    if not png_bytes:
        res = supervisor.capture_full_desktop_screenshot()
        png_bytes = res[1] if isinstance(res, tuple) and res[0] else (res if isinstance(res, bytes) else None)

    if not png_bytes:
        res = {"success": False, "error": "Failed to capture screenshot in current environment."}
        if args.json:
            print(json.dumps(res))
        else:
            print("ERROR: Could not capture screenshot.", file=sys.stderr)
        sys.exit(1)

    out_path = Path(args.out).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(png_bytes)

    sha256 = hashlib.sha256(png_bytes).hexdigest()
    res = {
        "success": True,
        "scope": args.scope,
        "hwnd": hex(args.hwnd) if args.hwnd else None,
        "path": str(out_path),
        "size_bytes": len(png_bytes),
        "sha256": sha256,
    }

    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Screenshot saved to {out_path} ({len(png_bytes)} bytes, SHA-256: {sha256[:12]}...)")


if __name__ == "__main__":
    main()
