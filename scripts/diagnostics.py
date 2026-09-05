#!/usr/bin/env python3
"""
CLI utility to dump desktop diagnostics: monitor topology, window forensics, and CDP endpoints.
Usage:
    python -m scripts.diagnostics [--json]
"""

from __future__ import annotations
import argparse
import json
import os
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.native_supervisor import NativeSupervisor
from runtime.coordinate_transform import CoordinateTransformer


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect and dump desktop system diagnostics.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    supervisor = NativeSupervisor()
    displays = supervisor.get_monitor_topology()

    windows = []
    for h in supervisor.list_top_level_windows(visible_only=True):
        try:
            insp = supervisor.inspect_window(h)
            windows.append({
                "hwnd": h,
                "hwnd_hex": hex(h),
                "title": insp.title,
                "pid": insp.pid,
                "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                "is_visible": insp.is_visible,
                "is_cloaked": insp.is_cloaked,
                "is_iconic": insp.is_iconic,
            })
        except Exception:
            continue

    diag = {
        "monitor_topology": [m.to_dict() for m in displays],
        "total_monitors": len(displays),
        "visible_windows": windows,
        "total_windows": len(windows),
    }

    if args.json:
        print(json.dumps(diag, indent=2))
    else:
        print(f"=== Desktop Topology & Forensics ===")
        print(f"Physical Monitors ({len(displays)}):")
        for m in displays:
            primary_tag = " [PRIMARY]" if m.is_primary else ""
            print(f"  Monitor {m.monitor_id}{primary_tag}: bounds=({m.bounds.x},{m.bounds.y},{m.bounds.width}x{m.bounds.height}) scale={m.dpi_scale:.2f}")

        print(f"\nVisible Windows ({len(windows)}):")
        for w in windows[:15]:
            print(f"  {w['hwnd_hex']} (PID: {w['pid']}): '{w['title']}' bounds={w['bounds']} cloaked={w['is_cloaked']}")


if __name__ == "__main__":
    main()
