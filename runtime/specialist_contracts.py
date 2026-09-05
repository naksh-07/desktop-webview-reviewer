"""
Specialist Agent Contracts & Subordination Boundaries (Architecture H).
Defines formal operational contracts for subordinate specialists:
Explorer, Tester, Reality Inspector, Debugger, and Evidence Specialist.
Enforces the Anti-God-Agent rule: specialists operate strictly inside delegated boundaries.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Set, Any


class SpecialistRole(str, Enum):
    """The five canonical subordinate specialist roles."""
    EXPLORER = "EXPLORER"
    TESTER = "TESTER"
    REALITY_INSPECTOR = "REALITY_INSPECTOR"
    DEBUGGER = "DEBUGGER"
    EVIDENCE_SPECIALIST = "EVIDENCE_SPECIALIST"


@dataclass(frozen=True)
class SpecialistContract:
    """
    Formal operational contract governing a specialist subagent.
    Defines its primary technical question, mandate, permitted tools, and strict non-scope.
    """
    role: SpecialistRole
    core_question: str
    mandate: str
    permitted_tools: Set[str]
    forbidden_operations: Set[str]
    is_read_only: bool = False
    requires_orchestrator_approval_to_act: bool = True

    def validate_tool_access(self, tool_name: str) -> bool:
        """Validates whether this specialist role is authorized to call a specific tool."""
        return tool_name in self.permitted_tools

    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role.value if isinstance(self.role, SpecialistRole) else str(self.role),
            "core_question": self.core_question,
            "mandate": self.mandate,
            "permitted_tools": sorted(list(self.permitted_tools)),
            "forbidden_operations": sorted(list(self.forbidden_operations)),
            "is_read_only": self.is_read_only,
            "requires_orchestrator_approval_to_act": self.requires_orchestrator_approval_to_act,
        }


class SpecialistRegistry:
    """Standard registry providing canonical contracts for subordinate specialists."""

    @classmethod
    def get_explorer_contract(cls) -> SpecialistContract:
        return SpecialistContract(
            role=SpecialistRole.EXPLORER,
            core_question="What exists in the application right now?",
            mandate="Enumerate windows, webview targets, frames, elements, and layout topology.",
            permitted_tools={
                "desktop_inspect",
                "desktop_screenshot",
                "desktop_query_targets",
                "desktop_get_tree",
                "desktop_get_capabilities",
            },
            forbidden_operations={
                "autonomous_mission_expansion",
                "unauthorized_state_mutation",
                "launching_unrelated_processes",
            },
            is_read_only=True,
            requires_orchestrator_approval_to_act=True,
        )

    @classmethod
    def get_tester_contract(cls) -> SpecialistContract:
        return SpecialistContract(
            role=SpecialistRole.TESTER,
            core_question="Did the explicitly requested workflow work?",
            mandate="Execute delegated interaction sequences, monitor settlement, and verify explicit assertions.",
            permitted_tools={
                "desktop_inspect",
                "desktop_click",
                "desktop_type",
                "desktop_press_key",
                "desktop_hover",
                "desktop_scroll",
                "desktop_settle",
                "desktop_assert",
                "desktop_screenshot",
                "desktop_get_evidence",
            },
            forbidden_operations={
                "inventing_new_business_workflows",
                "exploring_unrelated_screens",
                "bypassing_failed_assertions",
            },
            is_read_only=False,
            requires_orchestrator_approval_to_act=False,  # Authorized for delegated workflow
        )

    @classmethod
    def get_reality_inspector_contract(cls) -> SpecialistContract:
        return SpecialistContract(
            role=SpecialistRole.REALITY_INSPECTOR,
            core_question="What does the human user physically see on screen?",
            mandate="Inspect DWM compositor state, window occlusion, physical rendering, and screen framebuffer.",
            permitted_tools={
                "desktop_inspect",
                "desktop_screenshot",
                "desktop_crop",
                "desktop_diff",
                "desktop_get_window_forensics",
            },
            forbidden_operations={
                "dispatching_synthetic_input",
                "relying_solely_on_dom_visibility",
                "modifying_application_state",
            },
            is_read_only=True,
            requires_orchestrator_approval_to_act=True,
        )

    @classmethod
    def get_debugger_contract(cls) -> SpecialistContract:
        return SpecialistContract(
            role=SpecialistRole.DEBUGGER,
            core_question="Why did this interaction or assertion fail?",
            mandate="Correlate trace events, inspect console errors, evaluate UI thread responsiveness, and classify root cause.",
            permitted_tools={
                "desktop_inspect",
                "desktop_get_trace",
                "desktop_get_logs",
                "desktop_evaluate",
                "desktop_handle_dialog",
                "desktop_get_window_forensics",
            },
            forbidden_operations={
                "blind_retries_without_diagnosis",
                "modifying_test_acceptance_criteria",
                "closing_crashed_windows_without_evidence",
            },
            is_read_only=False,  # May evaluate debug scripts or dismiss modal dialogs
            requires_orchestrator_approval_to_act=True,
        )

    @classmethod
    def get_evidence_specialist_contract(cls) -> SpecialistContract:
        return SpecialistContract(
            role=SpecialistRole.EVIDENCE_SPECIALIST,
            core_question="Can we cryptographically prove what happened?",
            mandate="Compile evidence packages, verify SHA-256 hashes, validate byte-level immutability, and generate manifests.",
            permitted_tools={
                "desktop_get_evidence",
                "desktop_verify_manifest",
                "desktop_export_package",
            },
            forbidden_operations={
                "modifying_persisted_artifacts",
                "suppressing_unverified_verdicts",
                "faking_hashes",
            },
            is_read_only=True,
            requires_orchestrator_approval_to_act=True,
        )

    @classmethod
    def get_contract(cls, role: SpecialistRole) -> SpecialistContract:
        mapping = {
            SpecialistRole.EXPLORER: cls.get_explorer_contract(),
            SpecialistRole.TESTER: cls.get_tester_contract(),
            SpecialistRole.REALITY_INSPECTOR: cls.get_reality_inspector_contract(),
            SpecialistRole.DEBUGGER: cls.get_debugger_contract(),
            SpecialistRole.EVIDENCE_SPECIALIST: cls.get_evidence_specialist_contract(),
        }
        return mapping[role]
