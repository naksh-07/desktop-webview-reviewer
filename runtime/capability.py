"""
Capability negotiation and feature matrix model for Desktop WebView Reviewer.
Inspects connected targets and dynamically reports accurate capability states
without overclaiming support.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any, List, Set


class CapabilityCategory(str, Enum):
    PROCESS = "PROCESS"
    NATIVE = "NATIVE"
    WEBVIEW = "WEBVIEW"
    CDP = "CDP"
    SCREENSHOTS = "SCREENSHOTS"
    INPUT = "INPUT"
    OBSERVATION = "OBSERVATION"
    DIAGNOSTICS = "DIAGNOSTICS"
    EVIDENCE = "EVIDENCE"


class CapabilityStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
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
    NATIVE_UIA3 = "native.uia3"

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
    """

    def __init__(self):
        self._entries: Dict[CapabilityId, CapabilityEntry] = {}
        self._initialize_defaults()

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
            (CapabilityId.NATIVE_UIA3, CapabilityCategory.NATIVE),
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
        ]
        for cap_id, cat in defaults:
            self._entries[cap_id] = CapabilityEntry(cap_id=cap_id, category=cat)

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
                ("webview.", CapabilityCategory.WEBVIEW),
                ("screenshots.", CapabilityCategory.SCREENSHOTS),
                ("input.", CapabilityCategory.INPUT),
                ("observation.", CapabilityCategory.OBSERVATION),
                ("evidence.", CapabilityCategory.EVIDENCE),
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
        """Returns True only if the capability is explicitly SUPPORTED."""
        return self.get_status(cap_id) == CapabilityStatus.SUPPORTED

    def get_category_capabilities(self, category: CapabilityCategory) -> List[CapabilityEntry]:
        """Returns all capabilities in the given category."""
        return [e for e in self._entries.values() if e.category == category]

    def supported_capabilities(self) -> Set[CapabilityId]:
        """Returns the set of all capabilities currently in SUPPORTED status."""
        return {e.cap_id for e in self._entries.values() if e.status == CapabilityStatus.SUPPORTED}

    def to_dict(self) -> Dict[str, Any]:
        """Serializes the entire matrix to a structured dictionary."""
        return {
            cap_id.value: entry.to_dict()
            for cap_id, entry in self._entries.items()
        }
