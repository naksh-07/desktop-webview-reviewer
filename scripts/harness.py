#!/usr/bin/env python3
"""
CLI Utility for Reviewer Test Harness Management (Phases 13–14).
Provides developer-facing operations:
    desktop-reviewer harness init [--project-path DIR] [--dry-run] [--json]
    desktop-reviewer harness inspect [--project-path DIR] [--json]
    desktop-reviewer harness validate [--project-path DIR] [--json]
    desktop-reviewer harness remove [--project-path DIR] [--json]
    desktop-reviewer harness validate-release <artifact_path> [--json]
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from pathlib import Path

SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SKILL_ROOT not in sys.path:
    sys.path.insert(0, SKILL_ROOT)

from runtime.harness.detector import ProjectDetector
from runtime.harness.injector import HarnessInjector
from runtime.harness.manifest import IntegrationManifest
from runtime.harness.build_pipeline import ReleaseSecurityValidator


def cmd_init(args) -> int:
    project_dir = Path(args.project_path or ".").resolve()
    try:
        plan = HarnessInjector.plan(project_dir, framework_override=args.framework)
        manifest, report = HarnessInjector.apply(plan, dry_run=args.dry_run)

        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("Reviewer Harness")
            print("────────────────────────")
            print(f"Project:         {plan.project_path}")
            print(f"Framework:       {plan.framework}")
            print(f"Adapter:         {plan.adapter_name}")
            print()
            for cap, status in plan.capabilities.items():
                print(f"{cap.capitalize():<16} {status}")
            print()
            print(f"Files added:     {len(report['files_added'])}")
            for f in report['files_added']:
                print(f"  + {f}")
            print(f"Files changed:   {len(report['files_modified'])}")
            for f in report['files_modified']:
                print(f"  * {f}")
            if report.get("warnings"):
                print("Warnings:")
                for w in report["warnings"]:
                    print(f"  ! {w}")
            print()
            print(f"Status:          {'PREVIEW (dry-run)' if args.dry_run else 'READY'}")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_inspect(args) -> int:
    project_dir = Path(args.project_path or ".").resolve()
    detection = ProjectDetector.detect(project_dir)
    manifest = IntegrationManifest.load(project_dir)

    result = {
        "project_dir": str(project_dir),
        "detection": detection.to_dict(),
        "manifest": manifest.to_dict() if manifest else None,
        "is_integrated": manifest is not None,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("Reviewer Harness Inspection")
        print("────────────────────────")
        print(f"Project:         {project_dir.name}")
        print(f"Detected:        {detection.framework or 'None'} (confidence: {detection.confidence:.2f})")
        print(f"Adapter:         {detection.adapter or 'None'}")
        print(f"Integrated:      {'YES' if manifest else 'NO'}")
        if manifest:
            print(f"Integration Ver: {manifest.harness_version}")
            print(f"Files added:     {len(manifest.files_added)}")
            print(f"Files modified:  {len(manifest.files_modified)}")
            print(f"Status:          {manifest.validation_status}")
    return 0


def cmd_validate(args) -> int:
    project_dir = Path(args.project_path or ".").resolve()
    manifest = IntegrationManifest.load(project_dir)
    if not manifest:
        msg = f"Project at {project_dir} is not integrated with Reviewer Harness."
        if args.json:
            print(json.dumps({"valid": False, "error": msg}, indent=2))
        else:
            print(f"ERROR: {msg}", file=sys.stderr)
        return 1

    # Verify files exist
    missing = []
    for f in manifest.files_added:
        if not (project_dir / f).exists():
            missing.append(f)

    is_valid = len(missing) == 0
    res = {
        "valid": is_valid,
        "project": manifest.project,
        "framework": manifest.framework,
        "missing_files": missing,
        "status": "VALID" if is_valid else "CORRUPTED",
    }
    if args.json:
        print(json.dumps(res, indent=2))
    else:
        print(f"Validation: {'PASS' if is_valid else 'FAIL'}")
        if missing:
            print(f"Missing files: {missing}")
    return 0 if is_valid else 1


def cmd_remove(args) -> int:
    project_dir = Path(args.project_path or ".").resolve()
    try:
        report = HarnessInjector.remove(project_dir)
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print("Reviewer Harness Removed")
            print("────────────────────────")
            print(f"Files removed:   {len(report['files_removed'])}")
            for f in report['files_removed']:
                print(f"  - {f}")
            print(f"Files restored:  {len(report['files_restored'])}")
            for f in report['files_restored']:
                print(f"  ~ {f}")
            print("Status:          CLEAN")
        return 0
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_validate_release(args) -> int:
    artifact_path = Path(args.artifact).resolve()
    try:
        result = ReleaseSecurityValidator.scan_artifact(artifact_path)
        if args.json:
            print(json.dumps(result.to_dict(), indent=2))
        else:
            print("Reviewer Harness Release Security Gate")
            print("────────────────────────────────────────")
            print(f"Artifact:        {result.artifact_path}")
            print(f"Files scanned:   {result.scanned_files_count}")
            print(f"Verdict:         {result.verdict}")
            if not result.is_clean:
                print(f"VIOLATIONS DETECTED ({len(result.findings)}):")
                for f in result.findings:
                    print(f"  [{f.finding_type}] in {f.relative_path}")
                    print(f"    sample: {f.sample_text}")
                print()
                print("SECURITY AUDIT FAILED: Release artifact contains Reviewer Harness code/symbols.")
            else:
                print("SECURITY AUDIT PASSED: Zero Reviewer Harness artifacts or symbols found.")
        return 0 if result.is_clean else 1
    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e), "verdict": "FAIL"}, indent=2))
        else:
            print(f"ERROR: {e}", file=sys.stderr)
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="desktop-reviewer harness",
        description="Desktop WebView Reviewer Test Harness CLI (Architecture H).",
    )
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    # init
    p_init = subparsers.add_parser("init", help="Surgically integrate harness into an application project.")
    p_init.add_argument("--project-path", "-p", type=str, default=".", help="Project directory (default: current).")
    p_init.add_argument("--framework", "-f", type=str, default=None, help="Explicit framework override.")
    p_init.add_argument("--dry-run", action="store_true", help="Preview modifications without writing files.")
    p_init.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    p_init.set_defaults(func=cmd_init)

    # inspect
    p_inspect = subparsers.add_parser("inspect", help="Inspect project framework and harness status.")
    p_inspect.add_argument("--project-path", "-p", type=str, default=".", help="Project directory.")
    p_inspect.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    p_inspect.set_defaults(func=cmd_inspect)

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate harness integration integrity in dev build.")
    p_validate.add_argument("--project-path", "-p", type=str, default=".", help="Project directory.")
    p_validate.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    p_validate.set_defaults(func=cmd_validate)

    # remove
    p_remove = subparsers.add_parser("remove", help="Surgically reverse harness integration.")
    p_remove.add_argument("--project-path", "-p", type=str, default=".", help="Project directory.")
    p_remove.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    p_remove.set_defaults(func=cmd_remove)

    # validate-release
    p_val_rel = subparsers.add_parser("validate-release", help="Verify release artifact is 100%% free of harness code.")
    p_val_rel.add_argument("artifact", type=str, help="Path to release directory, bundle, or binary.")
    p_val_rel.add_argument("--json", action="store_true", help="Output machine-readable JSON.")
    p_val_rel.set_defaults(func=cmd_validate_release)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
