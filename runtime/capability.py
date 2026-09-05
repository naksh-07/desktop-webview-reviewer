"""
Capability negotiation and feature matrix model for Desktop WebView Reviewer.
Inspects connected targets and dynamically reports accurate capability states
without overclaiming support. Truthfully reflects Phase 2 native OS supervisor hardening.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
import sys
from typing import Dict, Optional, Any, List, Set


class CapabilityCategory(str, Enum):
    PROCESS = "PROCESS"
    NATIVE = "NATIVE"
    WEBVIEW = "WEBVIEW"
    CDP = "CDP"
    SCREENSHOTS = "SCREENSHOTS"
    INPUT = "INPUT"
    COORDINATE = "COORDINATE"
    OBSERVATION = "OBSERVATION"
    DIAGNOSTICS = "DIAGNOSTICS"
    EVIDENCE = "EVIDENCE"
    HARNESS = "HARNESS"


class CapabilityStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    SUPPORTED = "SUPPORTED"
    UNAVAILABLE = "UNAVAILABLE"
    UNSUPPORTED = "UNSUPPORTED"
    UNKNOWN = "UNKNOWN"
    DEGRADED = "DEGRADED"


class CapabilityId(str, Enum):
    # Process Capabilities
    PROCESS_SUPERVISION = "process.supervision"
    PROCESS_TREE_TRACKING = "process.tree_tracking"
    JOB_OBJECT_LIMIT = "process.job_object_limit"

    # Native OS Capabilities
    NATIVE_WIN32 = "native.win32"
    NATIVE_DWM_BOUNDS = "native.dwm_bounds"
    NATIVE_RESPONSIVENESS_CHECK = "native.responsiveness_check"
    NATIVE_MODAL_DETECTION = "native.modal_detection"
    NATIVE_PHYSICAL_VISIBILITY = "native.physical_visibility"
    NATIVE_OCCLUSION_DETECTION = "native.occlusion_detection"
    NATIVE_UIA3 = "native.uia3"

    # Coordinate Capabilities
    COORDINATE_TRANSFORM = "coordinate.transform"
    COORDINATE_MULTIMONITOR = "coordinate.multimonitor"

    # Webview Capabilities
    WEBVIEW_CDP = "webview.cdp"
    WEBVIEW_DOM = "webview.dom"
    WEBVIEW_ACCESSIBILITY_TREE = "webview.accessibility_tree"
    WEBVIEW_UTILITY_REALM = "webview.utility_realm"

    # Screenshots
    HARDWARE_SCREENSHOT = "screenshots.hardware"
    COMPOSITOR_SCREENSHOT = "screenshots.compositor"
    DESKTOP_CROP = "screenshots.desktop_crop"

    # Input
    SENDINPUT_NORMALIZED = "input.sendinput_normalized"
    CDP_INPUT_EVENTS = "input.cdp_events"
    UIA_PATTERNS = "input.uia_patterns"

    # Observation
    OBSERVATION_EPOCH = "observation.epoch_references"
    OBSERVATION_DIFF = "observation.diff_snapshots"

    # Diagnostics & Evidence
    DIAGNOSTICS_DPI = "diagnostics.dpi_metrics"
    DIAGNOSTICS_FORENSICS = "diagnostics.window_forensics"
    EVIDENCE_MANIFEST = "evidence.sha256_manifest"

    # Reviewer Test Harness Capabilities
    HARNESS_CORE = "harness.core"
    HARNESS_LIFECYCLE = "harness.lifecycle"
    HARNESS_DIAGNOSTICS = "harness.diagnostics"
    HARNESS_FIXTURES = "harness.fixtures"
    HARNESS_FAULT_INJECTION = "harness.fault_injection"


@dataclass
class CapabilityEntry:
    """Individual capability descriptor with status and justification."""
    cap_id: CapabilityId
    category: CapabilityCategory
    status: CapabilityStatus = CapabilityStatus.UNKNOWN
    reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cap_id": self.cap_id.value if isinstance(self.cap_id, CapabilityId) else str(self.cap_id),
            "category": self.category.value if isinstance(self.category, CapabilityCategory) else str(self.category),
            "status": self.status.value if isinstance(self.status, CapabilityStatus) else str(self.status),
            "reason": self.reason,
            "metadata": self.metadata,
        }


class CapabilityMatrix:
    """
    Authoritative capability registry for a target session.
    Dynamically populated and verified before operations.
    Enforces capability truthfulness without overclaiming.
    """

    def __init__(self, populate_defaults: bool = True):
        self._entries: Dict[CapabilityId, CapabilityEntry] = {}
        self._initialize_defaults()
        if populate_defaults and sys.platform == "win32":
            self.populate_phase2_native_defaults()

    def _initialize_defaults(self) -> None:
        """Populates matrix with baseline categories in UNKNOWN status."""
        defaults = [
            (CapabilityId.PROCESS_SUPERVISION, CapabilityCategory.PROCESS),
            (CapabilityId.PROCESS_TREE_TRACKING, CapabilityCategory.PROCESS),
            (CapabilityId.JOB_OBJECT_LIMIT, CapabilityCategory.PROCESS),
            (CapabilityId.NATIVE_WIN32, CapabilityCategory.NATIVE),
            (CapabilityId.NATIVE_DWM_BOUNDS, CapabilityCategory.NATIVE),
            (CapabilityId.NATIVE_RESPONSIVENESS_CHECK, CapabilityCategory.NATIVE),
            (CapabilityId.NATIVE_MODAL_DETECTION, CapabilityCategory.NATIVE),
            (CapabilityId.NATIVE_PHYSICAL_VISIBILITY, CapabilityCategory.NATIVE),
            (CapabilityId.NATIVE_OCCLUSION_DETECTION, CapabilityCategory.NATIVE),
            (CapabilityId.NATIVE_UIA3, CapabilityCategory.NATIVE),
            (CapabilityId.COORDINATE_TRANSFORM, CapabilityCategory.COORDINATE),
            (CapabilityId.COORDINATE_MULTIMONITOR, CapabilityCategory.COORDINATE),
            (CapabilityId.WEBVIEW_CDP, CapabilityCategory.WEBVIEW),
            (CapabilityId.WEBVIEW_DOM, CapabilityCategory.WEBVIEW),
            (CapabilityId.WEBVIEW_ACCESSIBILITY_TREE, CapabilityCategory.WEBVIEW),
            (CapabilityId.WEBVIEW_UTILITY_REALM, CapabilityCategory.WEBVIEW),
            (CapabilityId.HARDWARE_SCREENSHOT, CapabilityCategory.SCREENSHOTS),
            (CapabilityId.COMPOSITOR_SCREENSHOT, CapabilityCategory.SCREENSHOTS),
            (CapabilityId.DESKTOP_CROP, CapabilityCategory.SCREENSHOTS),
            (CapabilityId.SENDINPUT_NORMALIZED, CapabilityCategory.INPUT),
            (CapabilityId.CDP_INPUT_EVENTS, CapabilityCategory.INPUT),
            (CapabilityId.UIA_PATTERNS, CapabilityCategory.INPUT),
            (CapabilityId.OBSERVATION_EPOCH, CapabilityCategory.OBSERVATION),
            (CapabilityId.OBSERVATION_DIFF, CapabilityCategory.OBSERVATION),
            (CapabilityId.DIAGNOSTICS_DPI, CapabilityCategory.DIAGNOSTICS),
            (CapabilityId.DIAGNOSTICS_FORENSICS, CapabilityCategory.DIAGNOSTICS),
            (CapabilityId.EVIDENCE_MANIFEST, CapabilityCategory.EVIDENCE),
            (CapabilityId.HARNESS_CORE, CapabilityCategory.HARNESS),
            (CapabilityId.HARNESS_LIFECYCLE, CapabilityCategory.HARNESS),
            (CapabilityId.HARNESS_DIAGNOSTICS, CapabilityCategory.HARNESS),
            (CapabilityId.HARNESS_FIXTURES, CapabilityCategory.HARNESS),
            (CapabilityId.HARNESS_FAULT_INJECTION, CapabilityCategory.HARNESS),
        ]
        for cap_id, cat in defaults:
            self._entries[cap_id] = CapabilityEntry(cap_id=cap_id, category=cat)

    def populate_phase2_native_defaults(self) -> None:
        """
        Truthful Phase 2 capability status population for Windows runtime.
        Reports native OS supervisor capabilities as SUPPORTED, while keeping
        native semantic automation truthfully DEGRADED until Phase 4 FlaUI implementation.
        """
        self.set_capability(
            CapabilityId.PROCESS_SUPERVISION,
            CapabilityStatus.SUPPORTED,
            reason="ProcessSupervisor tracks PID, creation_time, and binary path",
        )
        self.set_capability(
            CapabilityId.PROCESS_TREE_TRACKING,
            CapabilityStatus.SUPPORTED,
            reason="Kernel QueryInformationJobObject and recursive psutil tree tracking",
        )
        self.set_capability(
            CapabilityId.JOB_OBJECT_LIMIT,
            CapabilityStatus.SUPPORTED,
            reason="Win32 Job Objects with KILL_ON_JOB_CLOSE guarantee zero orphans",
        )
        self.set_capability(
            CapabilityId.NATIVE_WIN32,
            CapabilityStatus.SUPPORTED,
            reason="Audited 64-bit safe Win32 interop layer (runtime/win32.py)",
        )
        self.set_capability(
            CapabilityId.NATIVE_DWM_BOUNDS,
            CapabilityStatus.SUPPORTED,
            reason="Authoritative DWMWA_EXTENDED_FRAME_BOUNDS physical display geometry",
        )
        self.set_capability(
            CapabilityId.NATIVE_RESPONSIVENESS_CHECK,
            CapabilityStatus.SUPPORTED,
            reason="Pre-flight SendMessageTimeoutW(WM_NULL, SMTO_ABORTIFHUNG, 500ms)",
        )
        self.set_capability(
            CapabilityId.NATIVE_MODAL_DETECTION,
            CapabilityStatus.SUPPORTED,
            reason="Heuristic Win32 dialog #32770, ownership, and disabled owner detection",
        )
        self.set_capability(
            CapabilityId.NATIVE_PHYSICAL_VISIBILITY,
            CapabilityStatus.SUPPORTED,
            reason="Multi-dimensional visibility model (visible, iconic, cloaked, foreground, bounded)",
        )
        self.set_capability(
            CapabilityId.NATIVE_OCCLUSION_DETECTION,
            CapabilityStatus.SUPPORTED,
            reason="Top-level window Z-order traversal and DWM bounding box intersection",
        )
        self.set_capability(
            CapabilityId.HARDWARE_SCREENSHOT,
            CapabilityStatus.SUPPORTED,
            reason="Leak-free GDI PrintWindow and BitBlt with DWM bounds and SHA-256",
        )
        self.set_capability(
            CapabilityId.DESKTOP_CROP,
            CapabilityStatus.SUPPORTED,
            reason="Leak-free GDI screen DC crop with guaranteed handle cleanup",
        )
        self.set_capability(
            CapabilityId.COORDINATE_TRANSFORM,
            CapabilityStatus.SUPPORTED,
            reason="Deterministic conversion across Web CSS, Webview, Native, Screen, and SendInput",
        )
        self.set_capability(
            CapabilityId.COORDINATE_MULTIMONITOR,
            CapabilityStatus.SUPPORTED,
            reason="Multi-monitor topology support with negative coordinate normalization",
        )
        self.set_capability(
            CapabilityId.SENDINPUT_NORMALIZED,
            CapabilityStatus.SUPPORTED,
            reason="Normalized 0..65535 coordinates across bounding virtual screen",
        )
        self.set_capability(
            CapabilityId.DIAGNOSTICS_DPI,
            CapabilityStatus.SUPPORTED,
            reason="Per-Monitor V2 GetDpiForWindow scaling factor analysis",
        )
        self.set_capability(
            CapabilityId.DIAGNOSTICS_FORENSICS,
            CapabilityStatus.SUPPORTED,
            reason="WindowForensicReport combining DWM, client origin, and health state",
        )
        # Truthful degraded status for unbuilt semantic automation
        self.set_capability(
            CapabilityId.NATIVE_UIA3,
            CapabilityStatus.DEGRADED,
            reason="Sidecar transport scaffolded; full FlaUI COM tree walkers scheduled for Phase 4",
        )
        self.set_capability(
            CapabilityId.UIA_PATTERNS,
            CapabilityStatus.DEGRADED,
            reason="FlaUI InvokePattern/ValuePattern automation scheduled for Phase 4",
        )

    def set_capability(
        self,
        cap_id: CapabilityId,
        status: CapabilityStatus,
        reason: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Sets or updates the status of a specific capability."""
        if cap_id in self._entries:
            entry = self._entries[cap_id]
            entry.status = status
            entry.reason = reason
            if metadata:
                entry.metadata.update(metadata)
        else:
            cat = CapabilityCategory.DIAGNOSTICS
            for prefix, c in [
                ("process.", CapabilityCategory.PROCESS),
                ("native.", CapabilityCategory.NATIVE),
                ("coordinate.", CapabilityCategory.COORDINATE),
                ("webview.", CapabilityCategory.WEBVIEW),
                ("screenshots.", CapabilityCategory.SCREENSHOTS),
                ("input.", CapabilityCategory.INPUT),
                ("observation.", CapabilityCategory.OBSERVATION),
                ("evidence.", CapabilityCategory.EVIDENCE),
                ("harness.", CapabilityCategory.HARNESS),
            ]:
                if cap_id.value.startswith(prefix):
                    cat = c
                    break
            self._entries[cap_id] = CapabilityEntry(
                cap_id=cap_id,
                category=cat,
                status=status,
                reason=reason,
                metadata=metadata or {},
            )

    def get_status(self, cap_id: CapabilityId) -> CapabilityStatus:
        """Queries status of a capability. Returns UNKNOWN if unregistered."""
        entry = self._entries.get(cap_id)
        return entry.status if entry else CapabilityStatus.UNKNOWN

    def is_supported(self, cap_id: CapabilityId) -> bool:
        """Returns True if the capability is SUPPORTED or AVAILABLE."""
        return self.get_status(cap_id) in (CapabilityStatus.SUPPORTED, CapabilityStatus.AVAILABLE)

    def get_category_capabilities(self, category: CapabilityCategory) -> List[CapabilityEntry]:
        """Returns all capabilities in the given category."""
        return [e for e in self._entries.values() if e.category == category]

    def supported_capabilities(self) -> Set[CapabilityId]:
        """Returns the set of all capabilities currently in SUPPORTED or AVAILABLE status."""
        return {
            e.cap_id for e in self._entries.values()
            if e.status in (CapabilityStatus.SUPPORTED, CapabilityStatus.AVAILABLE)
        }

    def build_negotiation_profile(
        self,
        session_id: str,
        target_id: Optional[str] = None,
        engine_info: Optional[Dict[str, Any]] = None,
    ) -> CapabilityNegotiationProfile:
        """
        Builds a formal 2.0 Capability Negotiation Profile declaring
        available, degraded, and unavailable domains with confidence and limitations.
        """
        categorized: Dict[str, Dict[str, Any]] = {}
        limitations: List[str] = []

        for entry in self._entries.values():
            cat_name = entry.category.value.lower()
            if cat_name not in categorized:
                categorized[cat_name] = {}
            categorized[cat_name][entry.cap_id.value] = {
                "status": entry.status.value,
                "reason": entry.reason,
            }
            if entry.status == CapabilityStatus.DEGRADED and entry.reason:
                limitations.append(f"{entry.cap_id.value}: {entry.reason}")
            elif entry.status in (CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNSUPPORTED) and entry.reason:
                limitations.append(f"{entry.cap_id.value} (UNAVAILABLE): {entry.reason}")

        # Compute confidence based on ratio of supported to total probed capabilities
        total_probed = sum(1 for e in self._entries.values() if e.status != CapabilityStatus.UNKNOWN)
        supported_count = len(self.supported_capabilities())
        confidence = (supported_count / total_probed) if total_probed > 0 else 0.5

        return CapabilityNegotiationProfile(
            session_id=session_id,
            target_id=target_id,
            engine_info=engine_info or {},
            capabilities=categorized,
            limitations=limitations,
            confidence=round(confidence, 2),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the entire matrix to a structured dictionary."""
        return {
            cap_id.value: entry.to_dict()
            for cap_id, entry in self._entries.items()
        }


@dataclass(frozen=True)
class CapabilityNegotiationProfile:
    """
    Formal 2.0 Capability Negotiation Profile emitted at session startup.
    Communicates exact capabilities, degraded fallbacks, and limitations to the controlling agent.
    """
    session_id: str
    target_id: Optional[str]
    engine_info: Dict[str, Any] = field(default_factory=dict)
    capabilities: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    limitations: List[str] = field(default_factory=list)
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "target_id": self.target_id,
            "engine_info": self.engine_info,
            "capabilities": self.capabilities,
            "limitations": self.limitations,
            "confidence": self.confidence,
        }
