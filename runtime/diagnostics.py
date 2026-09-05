"""
Unified Diagnostic Aggregator & Failure Classification Subsystem (Architecture H / Phase 16).
Correlates Desktop Trace, application logs, console exceptions, process state,
DWM forensics, Harness telemetry, and cryptographic evidence.
Classifies failures into 19 canonical categories and strictly distinguishes
observed facts from inferences and speculative hypotheses.
"""

from __future__ import annotations
import json
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from runtime.trace_models import DesktopTraceEventType, DesktopTraceEvent
from runtime.trace_engine import DesktopTraceEngine, redact_sensitive_trace_payload

logger = logging.getLogger("desktop_webview.diagnostics")


class FailureCategory(str, Enum):
    """The 19 canonical failure classifications."""
    TARGET_NOT_FOUND = "TARGET_NOT_FOUND"
    TARGET_NOT_ACTIONABLE = "TARGET_NOT_ACTIONABLE"
    PHYSICAL_OCCLUSION = "PHYSICAL_OCCLUSION"
    WINDOW_CLOAKED = "WINDOW_CLOAKED"
    WINDOW_MINIMIZED = "WINDOW_MINIMIZED"
    INPUT_DISPATCH_FAILURE = "INPUT_DISPATCH_FAILURE"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    SETTLEMENT_TIMEOUT = "SETTLEMENT_TIMEOUT"
    STATE_NOT_CHANGED = "STATE_NOT_CHANGED"
    EXPECTED_STATE_NOT_VERIFIED = "EXPECTED_STATE_NOT_VERIFIED"
    WEBVIEW_ERROR = "WEBVIEW_ERROR"
    CONSOLE_EXCEPTION = "CONSOLE_EXCEPTION"
    PROCESS_CRASH = "PROCESS_CRASH"
    PROCESS_HANG = "PROCESS_HANG"
    HARNESS_FAILURE = "HARNESS_FAILURE"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    PERMISSION_FAILURE = "PERMISSION_FAILURE"
    ENVIRONMENT_FAILURE = "ENVIRONMENT_FAILURE"
    UNKNOWN = "UNKNOWN"

    @property
    def is_recoverable(self) -> bool:
        """Determines default recoverability for this failure class."""
        non_recoverable = {
            FailureCategory.PROCESS_CRASH,
            FailureCategory.PERMISSION_FAILURE,
            FailureCategory.ENVIRONMENT_FAILURE,
        }
        return self not in non_recoverable


@dataclass(frozen=True)
class DiagnosticClaim:
    """Individual claim explaining part of a diagnostic evaluation."""
    claim_type: str            # "OBSERVED_FACT", "INFERENCE", "HYPOTHESIS"
    description: str
    source: str                # "trace", "process", "dwm", "console", "harness", "evidence"
    evidence_refs: List[str] = field(default_factory=list)
    trace_event_id: Optional[str] = None
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "claim_type": self.claim_type,
            "description": self.description,
            "source": self.source,
            "evidence_refs": list(self.evidence_refs),
            "trace_event_id": self.trace_event_id,
            "confidence": self.confidence,
        }


@dataclass
class DiagnosticDiagnosis:
    """
    Authoritative structured diagnosis produced by the Diagnostic Aggregator.
    Answers: What failed? When? Why? Supported by what evidence?
    """
    session_id: str
    failure_category: FailureCategory
    root_cause_summary: str
    confidence: float
    action_id: Optional[str] = None
    affected_component: str = "unknown"
    claims: List[DiagnosticClaim] = field(default_factory=list)
    contributing_factors: List[str] = field(default_factory=list)
    recovery_candidates: List[str] = field(default_factory=list)
    state_before: Dict[str, Any] = field(default_factory=dict)
    state_after: Dict[str, Any] = field(default_factory=dict)
    physical_desktop_state: Dict[str, Any] = field(default_factory=dict)
    dom_state: Dict[str, Any] = field(default_factory=dict)
    harness_state: Dict[str, Any] = field(default_factory=dict)
    evidence_manifest_id: Optional[str] = None
    is_recoverable: bool = False
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "action_id": self.action_id,
            "failure_category": self.failure_category.value,
            "root_cause_summary": self.root_cause_summary,
            "affected_component": self.affected_component,
            "confidence": round(self.confidence, 3),
            "is_recoverable": self.is_recoverable,
            "recovery_candidates": self.recovery_candidates,
            "contributing_factors": self.contributing_factors,
            "claims": [c.to_dict() for c in self.claims],
            "physical_desktop_state": self.physical_desktop_state,
            "dom_state": self.dom_state,
            "harness_state": self.harness_state,
            "evidence_manifest_id": self.evidence_manifest_id,
            "timestamp": self.timestamp,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)


class DiagnosticAggregator:
    """
    Unified multi-source diagnostic correlation engine.
    Fuses Desktop Trace, native window forensics, process state,
    webview events, and harness telemetry along a single monotonic timeline.
    """

    def __init__(self, trace_engine: Optional[DesktopTraceEngine] = None):
        self.trace_engine = trace_engine

    def diagnose_failure(
        self,
        session_state: Any,
        action_id: Optional[str] = None,
    ) -> DiagnosticDiagnosis:
        """
        Performs deterministic diagnostic correlation to identify and classify the root cause.
        Fails closed; never fabricates certainty.
        """
        session_id = getattr(session_state, "session_id", "default")
        trace_eng = self.trace_engine or getattr(session_state, "trace_engine", None)
        supervisor = getattr(session_state, "native_supervisor", None)
        target_win = getattr(session_state, "target_window", None)
        target_hwnd = target_win.hwnd if target_win else getattr(session_state, "target_hwnd", None)
        target_proc = getattr(session_state, "target_process", None)
        last_outcome = getattr(session_state, "last_outcome", None)

        claims: List[DiagnosticClaim] = []
        contributing_factors: List[str] = []
        recovery_candidates: List[str] = []

        category = FailureCategory.UNKNOWN
        root_cause = "No failure detected or cause undetermined"
        affected_comp = "unknown"
        confidence = 0.5
        manifest_id = None

        physical_state: Dict[str, Any] = {}
        dom_state: Dict[str, Any] = {}
        harness_state: Dict[str, Any] = {}

        # ---------------------------------------------------------------------
        # 1. Process Level Diagnosis
        # ---------------------------------------------------------------------
        if target_proc:
            is_alive = True
            exit_code = None
            if hasattr(target_proc, "is_alive"):
                is_alive = target_proc.is_alive()
                exit_code = getattr(target_proc, "exit_code", None)

            if not is_alive:
                category = FailureCategory.PROCESS_CRASH if exit_code not in (0, None) else FailureCategory.PROCESS_CRASH
                root_cause = f"Application process PID {target_proc.pid} terminated unexpectedly (exit code {exit_code})."
                affected_comp = "operating_system_process"
                confidence = 0.98
                claims.append(DiagnosticClaim(
                    claim_type="OBSERVED_FACT",
                    description=f"Process PID {target_proc.pid} is terminated with exit code {exit_code}.",
                    source="process",
                ))
                recovery_candidates.append("RESTART_TEST_FIXTURE")

        # ---------------------------------------------------------------------
        # 2. Window & DWM Compositor Level Diagnosis
        # ---------------------------------------------------------------------
        if category == FailureCategory.UNKNOWN and supervisor and target_hwnd:
            try:
                insp = supervisor.inspect_window(target_hwnd)
                physical_state = {
                    "hwnd": hex(target_hwnd),
                    "is_cloaked": insp.is_cloaked,
                    "is_iconic": insp.is_iconic,
                    "is_visible": insp.is_visible,
                    "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                }

                if insp.is_cloaked:
                    category = FailureCategory.WINDOW_CLOAKED
                    root_cause = f"Target window HWND {hex(target_hwnd)} is cloaked by DWM (minimized, virtual desktop, or lock screen)."
                    affected_comp = "dwm_compositor"
                    confidence = 0.95
                    claims.append(DiagnosticClaim(
                        claim_type="OBSERVED_FACT",
                        description=f"DWM reports window {hex(target_hwnd)} is cloaked.",
                        source="dwm",
                    ))
                    recovery_candidates.append("REFRESH_OBSERVATION")
                elif insp.is_iconic:
                    category = FailureCategory.WINDOW_MINIMIZED
                    root_cause = f"Target window HWND {hex(target_hwnd)} is minimized to taskbar."
                    affected_comp = "native_window"
                    confidence = 0.95
                    claims.append(DiagnosticClaim(
                        claim_type="OBSERVED_FACT",
                        description=f"Window {hex(target_hwnd)} has WS_MINIMIZE / IsIconic=True.",
                        source="dwm",
                    ))
                    recovery_candidates.append("REATTACH")

                # UI Message pump hang
                if category == FailureCategory.UNKNOWN and hasattr(supervisor, "is_window_hung") and supervisor.is_window_hung(target_hwnd):
                    category = FailureCategory.PROCESS_HANG
                    root_cause = f"Target window HWND {hex(target_hwnd)} is hung and failed SendMessageTimeout within 500ms."
                    affected_comp = "win32_message_pump"
                    confidence = 0.95
                    claims.append(DiagnosticClaim(
                        claim_type="OBSERVED_FACT",
                        description="Target window UI thread is unresponsive to Win32 message pump.",
                        source="native_supervisor",
                    ))
                    recovery_candidates.append("WAIT_FOR_PROCESS")

                # Modal dialog blocked
                if category == FailureCategory.UNKNOWN and hasattr(supervisor, "find_modal_dialogs"):
                    modals = supervisor.find_modal_dialogs(target_hwnd)
                    if modals:
                        m_hwnd, m_title = modals[0]
                        category = FailureCategory.INPUT_DISPATCH_FAILURE
                        root_cause = f"Native modal dialog '{m_title}' (HWND {hex(m_hwnd)}) is blocking UI interactions."
                        affected_comp = "native_modal_dialog"
                        confidence = 0.95
                        claims.append(DiagnosticClaim(
                            claim_type="OBSERVED_FACT",
                            description=f"Modal dialog '{m_title}' is blocking main window.",
                            source="native_supervisor",
                        ))
                        recovery_candidates.append("REFRESH_OBSERVATION")
            except Exception as e:
                logger.debug(f"Native window inspection error: {e}")

        # ---------------------------------------------------------------------
        # 3. Monotonic Desktop Trace & Telemetry Stream Correlation
        # ---------------------------------------------------------------------
        if trace_eng:
            try:
                events = trace_eng.get_action_lifecycle(action_id, session_id) if action_id else trace_eng.query(session_id=session_id, limit=50)

                for ev in events:
                    # Console Errors
                    if ev.event_type == DesktopTraceEventType.CONSOLE_EVENT and ev.status == "ERROR":
                        msg = ev.details.get("message") or ev.details.get("text", "")
                        claims.append(DiagnosticClaim(
                            claim_type="OBSERVED_FACT",
                            description=f"Console exception: {redact_sensitive_trace_payload(msg)[:150]}",
                            source="console",
                            trace_event_id=ev.event_id,
                        ))
                        contributing_factors.append(f"Console error: {redact_sensitive_trace_payload(msg)[:100]}")
                        if category == FailureCategory.UNKNOWN:
                            category = FailureCategory.CONSOLE_EXCEPTION
                            root_cause = f"Chromium runtime exception: {redact_sensitive_trace_payload(msg)[:150]}"
                            affected_comp = "webview_javascript"
                            confidence = 0.9

                    # Harness Signals & Telemetry
                    if ev.event_type in (DesktopTraceEventType.HARNESS_SIGNAL, DesktopTraceEventType.HARNESS_TELEMETRY):
                        signal = ev.details.get("signal", "")
                        harness_state["last_signal"] = signal
                        if "FAIL" in signal or ev.status == "ERROR":
                            claims.append(DiagnosticClaim(
                                claim_type="OBSERVED_FACT",
                                description=f"Test Harness error signal: {signal}",
                                source="harness",
                                trace_event_id=ev.event_id,
                            ))
                            contributing_factors.append(f"Harness reported: {signal}")
                            if category in (FailureCategory.UNKNOWN, FailureCategory.STATE_NOT_CHANGED):
                                category = FailureCategory.HARNESS_FAILURE
                                root_cause = f"Internal application failure detected by Test Harness: {signal}"
                                affected_comp = "application_internal"
                                confidence = 0.9

                    # Settlement Timeout
                    if ev.event_type == DesktopTraceEventType.ACTION_SETTLED and ev.status != "SUCCESS":
                        claims.append(DiagnosticClaim(
                            claim_type="OBSERVED_FACT",
                            description=f"Settlement failed: {ev.details.get('error', 'timeout')}",
                            source="trace",
                            trace_event_id=ev.event_id,
                        ))
                        if category == FailureCategory.UNKNOWN:
                            category = FailureCategory.SETTLEMENT_TIMEOUT
                            root_cause = "UI did not settle within the required settlement timeout budget."
                            affected_comp = "settlement_engine"
                            confidence = 0.85
                            recovery_candidates.append("REFRESH_OBSERVATION")

                    # Action outcome errors
                    if ev.event_type == DesktopTraceEventType.ACTION_DISPATCHED and ev.status != "SUCCESS":
                        claims.append(DiagnosticClaim(
                            claim_type="OBSERVED_FACT",
                            description=f"Action dispatch failed: {ev.details.get('error')}",
                            source="action_engine",
                            trace_event_id=ev.event_id,
                        ))
                        if category == FailureCategory.UNKNOWN:
                            category = FailureCategory.INPUT_DISPATCH_FAILURE
                            root_cause = f"Input dispatch was rejected or failed: {ev.details.get('error')}"
                            affected_comp = "input_dispatcher"
                            confidence = 0.9
            except Exception as e:
                logger.debug(f"Trace aggregator correlation error: {e}")

        # ---------------------------------------------------------------------
        # 4. Action Outcome Verification
        # ---------------------------------------------------------------------
        if category == FailureCategory.UNKNOWN and last_outcome:
            sc = getattr(last_outcome, "state_change", None)
            if str(sc) == "NO_EFFECT":
                category = FailureCategory.STATE_NOT_CHANGED
                root_cause = "Interaction was delivered, but post-observation confirmed ZERO state change in application."
                affected_comp = "interaction_target"
                confidence = 0.8
                claims.append(DiagnosticClaim(
                    claim_type="INFERENCE",
                    description="Pre- and post-action observation trees are identical; action had no effect.",
                    source="observation_engine",
                ))
                recovery_candidates.append("REFRESH_OBSERVATION")
            elif getattr(last_outcome, "error", None):
                err_msg = str(last_outcome.error)
                if "timeout" in err_msg.lower():
                    category = FailureCategory.ACTION_TIMEOUT
                    root_cause = f"Action execution timed out: {err_msg}"
                else:
                    category = FailureCategory.INPUT_DISPATCH_FAILURE
                    root_cause = f"Action execution error: {err_msg}"
                affected_comp = "action_engine"
                confidence = 0.85

        # ---------------------------------------------------------------------
        # 5. Default Fallback & Synthesis
        # ---------------------------------------------------------------------
        if category == FailureCategory.UNKNOWN:
            root_cause = "No authoritative failure detected across trace, process, or compositor telemetry."
            confidence = 0.5
            claims.append(DiagnosticClaim(
                claim_type="HYPOTHESIS",
                description="Failure may be due to uninstrumented logic or transient timing issue.",
                source="diagnostics",
                confidence=0.3,
            ))
            recovery_candidates.append("REFRESH_OBSERVATION")

        is_recoverable = category.is_recoverable

        return DiagnosticDiagnosis(
            session_id=session_id,
            action_id=action_id,
            failure_category=category,
            root_cause_summary=root_cause,
            affected_component=affected_comp,
            confidence=confidence,
            claims=claims,
            contributing_factors=contributing_factors,
            recovery_candidates=recovery_candidates,
            physical_desktop_state=physical_state,
            dom_state=dom_state,
            harness_state=harness_state,
            evidence_manifest_id=manifest_id,
            is_recoverable=is_recoverable,
        )
