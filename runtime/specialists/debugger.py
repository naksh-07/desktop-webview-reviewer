"""
Debugger Specialist Subagent (Architecture H / Phase 15).
Mandate: "Why did this interaction or assertion fail?"
Correlates action lifecycle, Desktop Trace, console errors, stderr/stdout,
window forensics, process state, Harness diagnostics, and evidence.
Strictly distinguishes OBSERVED_FACT vs INFERENCE vs HYPOTHESIS vs UNKNOWN.
Forbids blind retries without diagnosis or modifying acceptance criteria.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistLifecycleState,
    SpecialistResultStatus,
    SpecialistResult,
)
from runtime.specialists.base import BaseSpecialistRuntime
from runtime.trace_models import DesktopTraceEventType

logger = logging.getLogger("desktop_webview.specialist.debugger")


class DebuggerSpecialist(BaseSpecialistRuntime):
    """Subordinate specialist answering: 'Why did this interaction or assertion fail?'"""

    @property
    def role(self) -> SpecialistRole:
        return SpecialistRole.DEBUGGER

    async def execute(self) -> SpecialistResult:
        self._record_lifecycle(SpecialistLifecycleState.RUNNING, "Correlating multi-source runtime diagnostics.")

        target_action_id = self.delegation.parameters.get("action_id") or self.delegation.parent_action_id
        session_id = self.session_state.session_id

        observed_facts: List[str] = []
        inferences: List[str] = []
        hypotheses: List[str] = []
        contributing_factors: List[str] = []
        recovery_candidates: List[str] = []
        evidence_refs: List[str] = []
        trace_refs: List[str] = []
        limitations: List[str] = []

        root_cause = "UNKNOWN"
        affected_component = "unknown"
        affected_action = target_action_id or "none"
        confidence = 0.5

        # ---------------------------------------------------------------------
        # 1. Inspect Process State
        # ---------------------------------------------------------------------
        target_proc = getattr(self.session_state, "target_process", None)
        is_process_alive = True
        exit_code = None
        if target_proc and hasattr(target_proc, "is_alive"):
            try:
                is_process_alive = target_proc.is_alive()
                if not is_process_alive:
                    exit_code = getattr(target_proc, "exit_code", None)
                    observed_facts.append(f"Target process PID {target_proc.pid} has terminated (exit_code={exit_code}).")
                    root_cause = "PROCESS_CRASH" if exit_code != 0 else "PROCESS_EXITED"
                    affected_component = "target_process"
                    recovery_candidates.append("RESTART_TEST_FIXTURE")
                    confidence = 0.95
            except Exception as e:
                limitations.append(f"Process check failed: {e}")

        # ---------------------------------------------------------------------
        # 2. Inspect Window Forensics / Responsiveness / Modal Dialog
        # ---------------------------------------------------------------------
        supervisor = getattr(self.session_state, "native_supervisor", None)
        target_win = getattr(self.session_state, "target_window", None)
        target_hwnd = target_win.hwnd if target_win else getattr(self.session_state, "target_hwnd", None)

        if supervisor and target_hwnd and is_process_alive:
            try:
                insp = supervisor.inspect_window(target_hwnd)
                if getattr(insp, "is_cloaked", False):
                    observed_facts.append(f"Window HWND {hex(target_hwnd)} is CLOAKED by DWM.")
                    contributing_factors.append("DWM cloaking prevents physical visibility and input delivery.")
                    if root_cause == "UNKNOWN":
                        root_cause = "WINDOW_CLOAKED"
                        affected_component = "native_window"
                        recovery_candidates.append("REFRESH_OBSERVATION")
                        confidence = 0.9
                if getattr(insp, "is_iconic", False):
                    observed_facts.append(f"Window HWND {hex(target_hwnd)} is MINIMIZED.")
                    contributing_factors.append("Window is minimized to taskbar.")
                    if root_cause == "UNKNOWN":
                        root_cause = "WINDOW_MINIMIZED"
                        affected_component = "native_window"
                        recovery_candidates.append("REATTACH")
                        confidence = 0.9

                # UI Thread Hang check
                if hasattr(supervisor, "is_window_hung") and supervisor.is_window_hung(target_hwnd):
                    observed_facts.append(f"Window HWND {hex(target_hwnd)} failed SendMessageTimeout(WM_NULL); UI thread is HUNG.")
                    root_cause = "PROCESS_HANG"
                    affected_component = "ui_message_pump"
                    recovery_candidates.append("WAIT_FOR_PROCESS")
                    confidence = 0.95

                # Unhandled Modal Dialog check (#32770)
                if hasattr(supervisor, "find_modal_dialogs"):
                    modals = supervisor.find_modal_dialogs(target_hwnd)
                    if modals:
                        m_hwnd, m_title = modals[0]
                        observed_facts.append(f"Active native modal dialog '{m_title}' (HWND {hex(m_hwnd)}) is blocking UI thread.")
                        contributing_factors.append("Modal dialog must be dismissed before child window receives input.")
                        if root_cause == "UNKNOWN":
                            root_cause = "NATIVE_MODAL_BLOCKED"
                            affected_component = "native_modal_dialog"
                            recovery_candidates.append("DISMISS_MODAL_DIALOG")
                            confidence = 0.95
            except Exception as e:
                limitations.append(f"Window forensics inspection error: {e}")

        # ---------------------------------------------------------------------
        # 3. Correlate Desktop Trace Events & Timeline
        # ---------------------------------------------------------------------
        trace_eng = self.trace_engine
        if trace_eng:
            try:
                events = trace_eng.get_action_lifecycle(target_action_id, session_id) if target_action_id else trace_eng.query(session_id=session_id, limit=30)
                for ev in events:
                    trace_refs.append(ev.event_id)
                    ev_type = ev.event_type.value if hasattr(ev.event_type, "value") else str(ev.event_type)

                    # Console errors
                    if ev.event_type == DesktopTraceEventType.CONSOLE_EVENT and ev.status == "ERROR":
                        msg = ev.details.get("message") or ev.details.get("text", "")
                        observed_facts.append(f"Chromium console error: {self.sanitize_untrusted_content(msg)}")
                        contributing_factors.append(f"Webview runtime emitted exception: {self.sanitize_untrusted_content(msg[:80])}")
                        if root_cause in ("UNKNOWN", "ACTION_TIMEOUT"):
                            root_cause = "CONSOLE_EXCEPTION"
                            affected_component = "webview_javascript"
                            confidence = 0.85

                    # Harness failures
                    if ev.event_type in (DesktopTraceEventType.HARNESS_SIGNAL, DesktopTraceEventType.HARNESS_TELEMETRY):
                        signal = ev.details.get("signal", "")
                        if "FAIL" in signal or ev.status == "ERROR":
                            observed_facts.append(f"Harness signal reported error: {signal}")
                            contributing_factors.append(f"Test harness diagnostic: {signal}")
                            if root_cause in ("UNKNOWN", "STATE_NOT_CHANGED"):
                                root_cause = "HARNESS_FAILURE"
                                affected_component = "application_internal"
                                confidence = 0.85

                    # Action outcome failures
                    if ev.event_type == DesktopTraceEventType.ACTION_SETTLED and ev.status != "SUCCESS":
                        observed_facts.append(f"Action failed settlement: {ev.details.get('error', 'settlement timeout')}")
                        if root_cause == "UNKNOWN":
                            root_cause = "SETTLEMENT_TIMEOUT"
                            affected_component = "settlement_engine"
                            recovery_candidates.append("REFRESH_OBSERVATION")
                            confidence = 0.8

                    # Log errors (stderr)
                    if ev.event_type == DesktopTraceEventType.LOG_EVENT and ev.details.get("stream") == "stderr":
                        txt = ev.details.get("text", "")
                        if txt:
                            observed_facts.append(f"Application stderr: {self.sanitize_untrusted_content(txt)}")
                            contributing_factors.append(f"Application logged error to stderr: {self.sanitize_untrusted_content(txt[:80])}")

            except Exception as e:
                limitations.append(f"Trace correlation error: {e}")

        # ---------------------------------------------------------------------
        # 4. Action Outcome State Change Evaluation
        # ---------------------------------------------------------------------
        last_outcome = getattr(self.session_state, "last_outcome", None)
        if last_outcome and root_cause == "UNKNOWN":
            sc = getattr(last_outcome, "state_change", None)
            if str(sc) == "NO_EFFECT":
                inferences.append("Action was dispatched to target, but post-observation confirmed zero state change.")
                root_cause = "STATE_NOT_CHANGED"
                affected_component = "action_target"
                recovery_candidates.append("REFRESH_OBSERVATION")
                confidence = 0.75
            elif getattr(last_outcome, "outcome_status", None) and str(last_outcome.outcome_status) == "REJECTED":
                err = getattr(last_outcome, "error", "") or "rejected"
                observed_facts.append(f"Action execution was rejected: {err}")
                root_cause = "INPUT_DISPATCH_FAILURE"
                confidence = 0.85

        # ---------------------------------------------------------------------
        # 5. Formulate Hypotheses if Root Cause still Unknown
        # ---------------------------------------------------------------------
        if root_cause == "UNKNOWN":
            if not is_process_alive:
                hypotheses.append("Application may have exited before action dispatch was acknowledged.")
            else:
                hypotheses.append("Target element affordance may have drifted outside visible viewport or interaction ref expired.")
                recovery_candidates.append("REFRESH_OBSERVATION")
                confidence = 0.4

        answer = (
            f"Debugger identified root cause '{root_cause}' with {confidence:.0%} confidence "
            f"affecting {affected_component} ({len(observed_facts)} verified fact(s), {len(inferences)} inference(s))."
        )

        return SpecialistResult(
            specialist_id=self.specialist_id,
            role=self.role,
            delegation_id=self.delegation.delegation_id,
            session_id=session_id,
            status=SpecialistResultStatus.SUCCESS if root_cause != "UNKNOWN" else SpecialistResultStatus.DEGRADED,
            answer=answer,
            observations={
                "root_cause": root_cause,
                "confidence": confidence,
                "affected_component": affected_component,
                "affected_action": affected_action,
                "observed_facts": observed_facts,
                "inferences": inferences,
                "hypotheses": hypotheses,
                "contributing_factors": contributing_factors,
                "recovery_candidates": recovery_candidates,
            },
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            limitations=limitations,
            confidence=confidence,
        )
