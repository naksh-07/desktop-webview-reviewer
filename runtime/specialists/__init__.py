"""
Specialist Subagents Package for Desktop WebView Reviewer (Architecture H).
Exports the 5 canonical subordinate specialist runtimes:
Explorer, Tester, Reality Inspector, Debugger, and Evidence Specialist.
"""

from runtime.specialists.base import (
    BaseSpecialistRuntime,
    SpecialistSecurityException,
    SpecialistTimeoutException,
    SpecialistCancelledException,
)
from runtime.specialists.explorer import ExplorerSpecialist
from runtime.specialists.tester import TesterSpecialist
from runtime.specialists.reality_inspector import RealityInspectorSpecialist
from runtime.specialists.debugger import DebuggerSpecialist
from runtime.specialists.evidence import EvidenceSpecialist

__all__ = [
    "BaseSpecialistRuntime",
    "SpecialistSecurityException",
    "SpecialistTimeoutException",
    "SpecialistCancelledException",
    "ExplorerSpecialist",
    "TesterSpecialist",
    "RealityInspectorSpecialist",
    "DebuggerSpecialist",
    "EvidenceSpecialist",
]
