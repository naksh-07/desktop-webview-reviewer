"""
CLI Handler for Desktop WebView Reviewer Version and Lifecycle/Update Operations.

Commands:
    desktop-reviewer version [--json]
    desktop-reviewer update check [--json]
    desktop-reviewer update install <version> [--json]
    desktop-reviewer update status [--json]
    desktop-reviewer update pin <version> [--json]
    desktop-reviewer update unpin [--json]
    desktop-reviewer update rollback [--json]
    desktop-reviewer update doctor [--json]
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import List, Optional

try:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
except Exception:
    pass

from core.version import get_version_info
from runtime.lifecycle import LifecycleDoctor, LifecycleUpdater


def format_version_output(as_json: bool = False) -> int:
    """Displays authoritative runtime version and environment metadata."""
    vinfo = get_version_info()
    if as_json:
        print(json.dumps(vinfo.to_dict(), indent=2))
        return 0

    print("=" * 65)
    print("        Desktop WebView Reviewer 2.0 -- Version Contract")
    print("=" * 65)
    print(f"Product Name:        {vinfo.product_name}")
    print(f"Product Version:     {vinfo.product_version}")
    print(f"Package Version:     {vinfo.package_version}")
    print(f"Installation Source: {vinfo.installation_source}")
    print(f"Git Commit:          {vinfo.git_commit or 'Not available (packaged release)'}")
    print(f"Runtime Path:        {vinfo.runtime_path}")
    print(f"MCP Executable:      {vinfo.mcp_executable or 'Not found on PATH'}")
    print(f"Skill Path:          {vinfo.skill_installation_path or 'Not discoverable'}")
    print("=" * 65)
    return 0


def cmd_version(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="desktop-reviewer version", description="Display authoritative version contract")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args(argv)
    return format_version_output(as_json=args.json)


def cmd_update(argv: Optional[List[str]] = None) -> int:
    """Dispatches `desktop-reviewer update <subcommand>`."""
    parser = argparse.ArgumentParser(
        prog="desktop-reviewer update",
        description="Manage product lifecycle, updates, pinning, and rollback",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Update subcommand")

    # update check
    p_check = subparsers.add_parser("check", help="Check for compatible release updates")
    p_check.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update install
    p_inst = subparsers.add_parser("install", help="Install an explicitly requested version safely")
    p_inst.add_argument("version", help="Semantic version to install (e.g. 2.0.1)")
    p_inst.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update status
    p_status = subparsers.add_parser("status", help="Show current installation and update status")
    p_status.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update pin
    p_pin = subparsers.add_parser("pin", help="Pin installation to a known-good version")
    p_pin.add_argument("version", help="Version to pin (e.g. 2.0.0)")
    p_pin.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update unpin
    p_unpin = subparsers.add_parser("unpin", help="Remove version pin and resume normal release channel")
    p_unpin.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update rollback
    p_roll = subparsers.add_parser("rollback", help="Roll back to previous known-good installation")
    p_roll.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    # update doctor
    p_doc = subparsers.add_parser("doctor", help="Run deep installation consistency checks")
    p_doc.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    args = parser.parse_args(argv)

    if not args.subcommand:
        parser.print_help()
        return 0

    updater = LifecycleUpdater()

    if args.subcommand == "check":
        res = updater.check_for_updates()
        if args.json:
            print(json.dumps(res.to_dict(), indent=2))
        else:
            print("Desktop WebView Reviewer -- Update Check")
            print("-" * 50)
            print(f"Installed Version:   {res.installed_version}")
            print(f"Channel:             {res.channel}")
            print(f"Lifecycle State:     {res.state.value}")
            if res.pinned_version:
                print(f"Pinned Version:      {res.pinned_version} (Updates suppressed)")
            print(f"Latest Compatible:   {res.latest_compatible_version or 'N/A'}")
            print(f"Update Available:    {'YES' if res.update_available else 'NO'}")
            print(f"Details:             {res.details}")
            if res.release_notes:
                print("\nRelease Notes Preview:")
                print(res.release_notes[:300] + ("..." if len(res.release_notes) > 300 else ""))
        return 0

    elif args.subcommand == "status":
        status_dict = updater.get_status()
        if args.json:
            print(json.dumps(status_dict, indent=2))
        else:
            print("Desktop WebView Reviewer -- Lifecycle Status")
            print("-" * 50)
            print(f"Installed Version:   {status_dict['installed_version']}")
            print(f"Lifecycle State:     {status_dict['lifecycle_state']}")
            print(f"Pinned Version:      {status_dict['pinned_version'] or 'None (Tracking ' + status_dict['channel'] + ')'}")
            print(f"Known-Good Version:  {status_dict['previous_known_good_version'] or 'None recorded'}")
            print(f"Rollback Available:  {'YES' if status_dict['rollback_available'] else 'NO'}")
            print(f"Latest Compatible:   {status_dict['latest_compatible_version'] or 'Up to date'}")
            print(f"Update Available:    {'YES' if status_dict['update_available'] else 'NO'}")
            print(f"Last Update Attempt: {status_dict['last_update_attempt'] or 'None'}")
            print(f"Last Validation:     {status_dict['last_successful_validation']}")
            skill_info = status_dict.get("skill", {})
            print(f"Skill Compatibility: {'COMPATIBLE' if skill_info.get('is_compatible') else 'ACTION REQUIRED'}")
            print(f"Skill Diagnosis:     {skill_info.get('diagnosis', 'N/A')}")
            exp_info = status_dict.get("experience_store")
            if exp_info:
                print(f"Experience Store:    {exp_info.get('health', 'UNKNOWN')} (Schema v{exp_info.get('schema_version', '?')} at {exp_info.get('storage_path', 'N/A')})")
        return 0

    elif args.subcommand == "pin":
        try:
            rec = updater.pin(args.version)
            if args.json:
                print(json.dumps({"success": True, "pinned_version": rec.pinned_version}, indent=2))
            else:
                print(f"Successfully pinned installation to version {rec.pinned_version}.")
                print("Automatic updates beyond this version are now suppressed.")
            return 0
        except Exception as e:
            if args.json:
                print(json.dumps({"success": False, "error": str(e)}, indent=2))
            else:
                print(f"Error setting pin: {e}", file=sys.stderr)
            return 1

    elif args.subcommand == "unpin":
        rec = updater.unpin()
        if args.json:
            print(json.dumps({"success": True, "pinned_version": None}, indent=2))
        else:
            print("Successfully unpinned installation.")
            print(f"Resumed normal release tracking on channel '{rec.channel}'.")
        return 0

    elif args.subcommand == "install":
        ok, msg = updater.install(args.version)
        if args.json:
            print(json.dumps({"success": ok, "message": msg, "target_version": args.version}, indent=2))
        else:
            if ok:
                print(f"PASS: {msg}")
            else:
                print(f"FAIL: {msg}", file=sys.stderr)
        return 0 if ok else 1

    elif args.subcommand == "rollback":
        ok, msg = updater.rollback()
        if args.json:
            print(json.dumps({"success": ok, "message": msg}, indent=2))
        else:
            if ok:
                print(f"PASS: {msg}")
            else:
                print(f"FAIL: {msg}", file=sys.stderr)
        return 0 if ok else 1

    elif args.subcommand == "doctor":
        doc = LifecycleDoctor(registry=updater.registry, skill_sync=updater.skill_sync)
        rep = doc.run_doctor()
        if args.json:
            print(json.dumps(rep.to_dict(), indent=2))
        else:
            print("Desktop WebView Reviewer -- Update & Installation Doctor")
            print("-" * 56)
            print(f"Installed Version: {rep.installed_version}")
            print(f"Runtime Location:  {rep.runtime_location}")
            print(f"Overall Health:    {'HEALTHY (PASS)' if rep.passed else 'ATTENTION REQUIRED (FAIL)'}")
            print("\nConsistency Checks:")
            for c in rep.checks:
                print(f"  [{c.status:<4}] {c.name:<28}: {c.message}")
        return 0 if rep.passed else 1

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    return cmd_update(argv)


if __name__ == "__main__":
    sys.exit(main())
