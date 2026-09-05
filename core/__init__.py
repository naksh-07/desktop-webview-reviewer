"""
Universal Desktop WebView Reviewer Core.
"""

from .models import (
    CapabilityName,
    CapabilityStatus,
    EngineInfo,
    EvidenceReport,
    NodeGeometry,
    Target,
    TargetCriteria,
)
from .capabilities import CapabilityRegistry
from .session import CDPSession
from .discovery import TargetDiscovery
from .actions import WebviewActions
from .assertions import WebviewAssertions, AssertionResult
from .evidence import EvidenceCollector
from .cleanup import ProcessCleanup

__version__ = "2.0.0"
__author__ = "Antigravity Team"

__all__ = [
    "__version__",
    "__author__",
    "CapabilityName",
    "CapabilityStatus",
    "EngineInfo",
    "EvidenceReport",
    "NodeGeometry",
    "Target",
    "TargetCriteria",
    "CapabilityRegistry",
    "CDPSession",
    "TargetDiscovery",
    "WebviewActions",
    "WebviewAssertions",
    "AssertionResult",
    "EvidenceCollector",
    "ProcessCleanup",
]

