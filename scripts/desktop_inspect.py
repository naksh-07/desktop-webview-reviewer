#!/usr/bin/env python3
"""
CLI utility to inspect desktop window hierarchy and reality model reconciliation.
Usage:
    python -m scripts.desktop_inspect [--hwnd HWND] [--reality] [--json]
"""

from __future__ import annotations
import argparse
import asyncio
import json
import os
import sys

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.observation_engine import ObservationEngine
from runtime.native_supervisor import NativeSupervisor
from runtime.references import ReferenceRegistry


async def run_inspect(hwnd: int | None, reality: bool, json_output: bool) -> None:
    supervisor = NativeSupervisor()
    registry = ReferenceRegistry()
    engine = ObservationEngine(
        session_id="cli_inspect_session",
        reference_registry=registry,
        native_supervisor=supervisor,
    )

    target_hwnd = hwnd
    if target_hwnd is None:
        top_hwnds = supervisor.list_top_level_windows(visible_only=True)
        if top_hwnds:
            target_hwnd = top_hwnds[0]

    if reality:
        reality_snap = await engine.observe_reality(hwnd=target_hwnd)
        data = reality_snap.to_dict()
        if json_output:
            print(json.dumps(data, indent=2))
        else:
            print(f"=== Reality Reconciliation Snapshot (Epoch {reality_snap.epoch}) ===")
            print(f"Target HWND: {hex(target_hwnd) if target_hwnd else 'None'}")
            print(f"Reconciled Targets: {len(reality_snap.targets)}")
            print(f"Contradictions: {len(reality_snap.contradictions)}")
            for c in reality_snap.contradictions:
                if isinstance(c, dict):
                    print(f"  [CONTRADICTION] {c.get('type', 'GENERAL')}: {c.get('description', str(c))}")
                else:
                    print(f"  [CONTRADICTION] {c}")
            print("\nReconciled Elements:")
            for t in reality_snap.targets[:20]:
                print(f"  {t.reference}: role={t.role} name='{t.name}' visible={t.is_physically_visible} actionable={t.actionability.is_actionable}")
    else:
        snapshot = await engine.observe(hwnd=target_hwnd)
        if json_output:
            print(json.dumps(snapshot.to_dict(), indent=2))
        else:
            print(f"=== Window Observation (Epoch {snapshot.epoch}) ===")
            print(f"Target HWND: {hex(target_hwnd) if target_hwnd else 'None'}")
            print(snapshot.text_representation)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect desktop UI state.")
    parser.add_argument("--hwnd", type=lambda x: int(x, 0), default=None, help="Target window HWND.")
    parser.add_argument("--reality", action="store_true", help="Perform multi-plane Reality Reconciliation under Truth Hierarchy.")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    args = parser.parse_args()

    asyncio.run(run_inspect(args.hwnd, args.reality, args.json))


if __name__ == "__main__":
    main()
