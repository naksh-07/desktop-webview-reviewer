#!/usr/bin/env python3
"""
CLI utility for Subordinate Specialists (Architecture H / Phase 15).
Usage:
    python -m scripts.specialists_cli list [--json]
    python -m scripts.specialists_cli contract <ROLE> [--json]
    python -m scripts.specialists_cli invoke --role <ROLE> --session <SESSION_ID> --task <TASK> [--tools <TOOL,...>] [--json]
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

from runtime.specialist_contracts import SpecialistRole, SpecialistRegistry
from runtime.specialist_models import SpecialistDelegation, DelegationScope
from runtime.specialist_dispatcher import SpecialistDispatcher
from runtime.session_manager import SessionManager


def main() -> int:
    parser = argparse.ArgumentParser(description="Subordinate Specialist Subagents CLI")
    subparsers = parser.add_subparsers(dest="subcommand", help="Specialist command")

    # 1. list
    list_p = subparsers.add_parser("list", help="List the 5 canonical subordinate specialists.")
    list_p.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    # 2. contract
    contract_p = subparsers.add_parser("contract", help="Display formal contract for a specialist role.")
    contract_p.add_argument("role", choices=[r.value for r in SpecialistRole], help="Specialist role name.")
    contract_p.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    # 3. invoke
    invoke_p = subparsers.add_parser("invoke", help="Invoke a specialist under an explicit delegation.")
    invoke_p.add_argument("--role", required=True, choices=[r.value for r in SpecialistRole], help="Specialist role.")
    invoke_p.add_argument("--session", required=True, help="Target session ID.")
    invoke_p.add_argument("--task", required=True, help="Specific technical question/task.")
    invoke_p.add_argument("--tools", help="Comma-separated list of permitted tools.")
    invoke_p.add_argument("--timeout", type=float, default=30.0, help="Timeout budget in seconds.")
    invoke_p.add_argument("--json", action="store_true", help="Output machine-readable JSON.")

    args = parser.parse_args()

    if args.subcommand == "list":
        roles = []
        for r in SpecialistRole:
            contract = SpecialistRegistry.get_contract(r)
            roles.append({
                "role": r.value,
                "core_question": contract.core_question,
                "mandate": contract.mandate,
                "is_read_only": contract.is_read_only,
                "permitted_tools": sorted(list(contract.permitted_tools)),
            })
        if args.json:
            print(json.dumps(roles, indent=2))
        else:
            print("=== Canonical Subordinate Specialists ===")
            for item in roles:
                ro = " [READ-ONLY]" if item["is_read_only"] else " [STATE-MUTATING]"
                print(f"- {item['role']}{ro}")
                print(f"  Question: {item['core_question']}")
                print(f"  Mandate:  {item['mandate']}")
                print(f"  Tools:    {', '.join(item['permitted_tools'])}")
                print()
        return 0

    elif args.subcommand == "contract":
        role_enum = SpecialistRole(args.role)
        contract = SpecialistRegistry.get_contract(role_enum)
        data = contract.to_dict()
        if args.json:
            print(json.dumps(data, indent=2))
        else:
            print(f"=== Specialist Contract: {args.role} ===")
            print(f"Core Question:        {contract.core_question}")
            print(f"Mandate:              {contract.mandate}")
            print(f"Read-Only:            {contract.is_read_only}")
            print(f"Permitted Tools:      {', '.join(sorted(list(contract.permitted_tools)))}")
            print(f"Forbidden Operations: {', '.join(sorted(list(contract.forbidden_operations)))}")
        return 0

    elif args.subcommand == "invoke":
        role_enum = SpecialistRole(args.role)
        contract = SpecialistRegistry.get_contract(role_enum)
        permitted_tools = set(args.tools.split(",")) if args.tools else contract.permitted_tools

        scope = DelegationScope(session_id=args.session)
        delegation = SpecialistDelegation(
            role=role_enum,
            task=args.task,
            scope=scope,
            permitted_tools=permitted_tools,
            timeout_sec=args.timeout,
        )

        session_mgr = SessionManager()
        dispatcher = SpecialistDispatcher(session_manager=session_mgr)

        async def _run():
            return await dispatcher.dispatch(delegation)

        result = asyncio.run(_run())
        if args.json:
            print(result.to_json())
        else:
            print(f"=== Specialist Result [{result.role.value}] ===")
            print(f"Status:     {result.status.value}")
            print(f"Answer:     {result.answer}")
            print(f"Confidence: {result.confidence:.0%}")
            print(f"Duration:   {result.duration_ms:.1f}ms")
            if result.errors:
                print(f"Errors:     {'; '.join(result.errors)}")
        return 0 if result.status.value == "SUCCESS" else 1

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
