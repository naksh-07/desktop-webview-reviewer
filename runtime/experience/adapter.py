"""
Thin Experience Integration Layer (Architecture H / 2.1 Prompt 2).

Connects authoritative runtime subsystems (SessionManager, MissionOrchestrator,
ActionExecutionEngine, DesktopTraceEngine, EvidenceStore, VerificationEngine,
DiagnosticAggregator, and RecoveryEngine) to the Experience Store.

Enforces:
- Historical consumer only: never replaces authoritative runtime/evidence/trace truth.
- Defensive fail-safe: persistence failure never halts or alters live desktop review.
- Strict privacy boundary: passes all records through PrivacyEnforcer.
- Tripartite verdict fidelity: PASS, FAIL, UNVERIFIED preserved without reinterpretation.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from core.version import get_version_info
from runtime.experience.models import (
    ActionReferenceRecord,
    EvidenceReferenceRecord,
    ExperienceScope,
    MissionExperienceRecord,
    NormalizedFailureRecord,
    OutcomeRecord,
    ProvenanceRecord,
    RecordKind,
    RecordSourceType,
    RecoveryExperienceRecord,
    SessionExperienceRecord,
    TraceReferenceRecord,
)
from runtime.experience.normalization import FailureNormalizer
from runtime.experience.privacy import PrivacyEnforcer
from runtime.experience.store import ExperienceStore
from runtime.trace_models import DesktopTraceEvent, DesktopTraceEventType

logger = logging.getLogger("desktop_webview.experience.adapter")

# Admitted trace event families for durable historical references (Section 9)
SIGNIFICANT_TRACE_EVENTS = {
    DesktopTraceEventType.APP_LAUNCH,
    DesktopTraceEventType.APP_ATTACH,
    DesktopTraceEventType.WINDOW_DISCOVERED,
    DesktopTraceEventType.PROCESS_STATE,
    DesktopTraceEventType.WEBVIEW_CONNECTED,
    DesktopTraceEventType.OBSERVATION,
    DesktopTraceEventType.TARGET_RESOLVED,
    DesktopTraceEventType.ACTION_REQUESTED,
    DesktopTraceEventType.ACTION_DISPATCHED,
    DesktopTraceEventType.ACTION_SETTLED,
    DesktopTraceEventType.SCREENSHOT,
    DesktopTraceEventType.DOM_CHANGE,
    DesktopTraceEventType.UIA_CHANGE,
    DesktopTraceEventType.CONSOLE_EVENT,
    DesktopTraceEventType.LOG_EVENT,
    DesktopTraceEventType.ASSERTION,
    DesktopTraceEventType.RECOVERY,
    DesktopTraceEventType.EVIDENCE_CREATED,
    DesktopTraceEventType.SPECIALIST_LIFECYCLE,
    DesktopTraceEventType.RECOVERY_ATTEMPT,
    DesktopTraceEventType.MISSION_LIFECYCLE,
    DesktopTraceEventType.MISSION_DISCOVERY,
    DesktopTraceEventType.MISSION_PLAN,
}
SIGNIFICANT_TRACE_EVENT_NAMES = {getattr(e, "value", str(e)) for e in SIGNIFICANT_TRACE_EVENTS}


class ExperienceIntegrationAdapter:
    """
    Thin integration adapter translating runtime events into durable Experience Store facts.
    Guarantees non-blocking or fail-safe execution: persistence failure will NEVER fail live actions.
    """

    _default_adapter: Optional[ExperienceIntegrationAdapter] = None
    _adapter_lock: threading.Lock = threading.Lock()

    def __init__(self, store: Optional[ExperienceStore] = None, bridge: Optional[Any] = None):
        self._store = store
        self._bridge = bridge
        self._lock = threading.RLock()

    @classmethod
    def get_default_adapter(cls) -> ExperienceIntegrationAdapter:
        with cls._adapter_lock:
            if cls._default_adapter is None:
                cls._default_adapter = cls()
            return cls._default_adapter

    @property
    def store(self) -> ExperienceStore:
        if self._store is None:
            self._store = ExperienceStore.get_default_store()
        return self._store

    def _get_bridge(self) -> Optional[Any]:
        if self._bridge is not None:
            return self._bridge
        try:
            from runtime.experience.antigravity import AntigravityCorrelationBridge
            return AntigravityCorrelationBridge.get_default_bridge()
        except Exception:
            return None

    def _notify_bridge_session(self, session_id: str, project_id: Optional[str] = None, conversation_id: Optional[str] = None) -> None:
        """Notifies optional Antigravity correlation bridge of DWR session lifecycle."""
        try:
            bridge = self._get_bridge()
            if bridge:
                bridge.on_dwr_session_started(session_id, project_id=project_id, conversation_id=conversation_id)
        except Exception as e:
            logger.debug("Antigravity bridge session notification skipped: %s", e)

    def _notify_bridge_mission(self, mission_id: str, session_id: str) -> None:
        """Notifies optional Antigravity correlation bridge of DWR mission lifecycle."""
        try:
            bridge = self._get_bridge()
            if bridge:
                bridge.on_dwr_mission_admitted(mission_id, session_id=session_id)
        except Exception as e:
            logger.debug("Antigravity bridge mission notification skipped: %s", e)

    def _notify_bridge_action(self, action_id: str, session_id: str, duration_ms: Optional[float] = None, action_type: Optional[str] = None) -> None:
        """Notifies optional Antigravity correlation bridge of DWR action settlement."""
        try:
            bridge = self._get_bridge()
            if bridge:
                bridge.on_dwr_action_settled(action_id, session_id, duration_ms=duration_ms, action_type=action_type)
        except Exception as e:
            logger.debug("Antigravity bridge action notification skipped: %s", e)

    # -------------------------------------------------------------------------
    # Session Lifecycle Integration
    # -------------------------------------------------------------------------

    def on_session_created(
        self,
        session_state: Any = None,
        *,
        session_id: Optional[str] = None,
        project_id: Optional[str] = None,
        target_executable: Optional[str] = None,
        target_pid: Optional[int] = None,
        target_hwnd: Optional[Union[int, str]] = None,
        active_plane: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionExperienceRecord]:
        """Translates session initialization into a durable SessionExperienceRecord."""
        try:
            vinfo = get_version_info()
            now_iso = datetime.now(timezone.utc).isoformat()

            if isinstance(session_state, str):
                if session_id is None:
                    session_id = session_state
                session_state = None

            if session_state is not None:
                sid = str(getattr(session_state, "session_id", session_id or "default_session"))
                target_proc = getattr(session_state, "target_process", None)
                target_win = getattr(session_state, "target_window", None)
                exe = target_executable or (getattr(target_proc, "executable", None) if target_proc else None)
                pid = target_pid if target_pid is not None else (getattr(target_proc, "pid", None) if target_proc else None)
                target_hwnd_obj = getattr(target_win, "hwnd", None) if target_win else None
                hwnd_val = hex(target_hwnd_obj) if isinstance(target_hwnd_obj, int) else (str(target_hwnd) if target_hwnd is not None else None)
                ap = getattr(session_state, "active_plane", None)
                plane = active_plane or (getattr(ap, "value", str(ap)) if ap is not None else "NATIVE")
                ls = getattr(session_state, "lifecycle_state", None)
                st = getattr(ls, "value", str(ls)) if ls is not None else "INITIALIZING"
                created_at_attr = getattr(session_state, "created_at", None)
                if created_at_attr is not None and hasattr(created_at_attr, "isoformat"):
                    cat = created_at_attr.isoformat()
                elif created_at_attr is not None:
                    cat = str(created_at_attr)
                else:
                    cat = now_iso
            else:
                sid = str(session_id or "default_session")
                exe = target_executable
                pid = target_pid
                hwnd_val = hex(target_hwnd) if isinstance(target_hwnd, int) else (str(target_hwnd) if target_hwnd is not None else None)
                plane = active_plane or "NATIVE"
                st = "INITIALIZING"
                cat = now_iso

            record = SessionExperienceRecord(
                session_id=sid,
                project_id=project_id,
                created_at=cat,
                status=st,
                runtime_version=vinfo.product_version,
                target_executable=exe,
                target_pid=pid,
                target_hwnd=hwnd_val,
                target_plane=plane,
                scope=ExperienceScope.SESSION,
                metadata=metadata or {},
            )
            rec = self.store.record_session(record)
            self._notify_bridge_session(
                session_id=sid,
                project_id=project_id,
                conversation_id=(metadata.get("conversation_id") if isinstance(metadata, dict) else None),
            )
            return rec
        except Exception as e:
            logger.warning("Graceful degradation: failed to persist session creation: %s", e)
            return None

    def on_session_activated(
        self,
        session_state: Any = None,
        *,
        session_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionExperienceRecord]:
        """Convenience callback when a session becomes RUNNING."""
        try:
            sid = session_id or (session_state if isinstance(session_state, str) else getattr(session_state, "session_id", None))
            if not sid:
                return None
            existing = self.store.get_session(sid)
            if existing:
                existing.status = "RUNNING"
                if metadata:
                    existing.metadata.update(metadata)
                return self.store.record_session(existing)
            return self.on_session_updated(session_state or sid, status="RUNNING", metadata=metadata)
        except Exception as e:
            logger.warning("Graceful degradation: failed to activate session in experience store: %s", e)
            return None

    def on_session_updated(
        self,
        session_state: Any,
        status: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionExperienceRecord]:
        """Updates an existing session record with new state or plane changes."""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            if isinstance(session_state, str):
                sid = session_state
                existing = self.store.get_session(sid)
                if existing:
                    if status:
                        existing.status = status
                    if metadata:
                        existing.metadata.update(metadata)
                    return self.store.record_session(existing)
                target_proc = None
                target_win = None
                plane = "NATIVE"
                st = status or "RUNNING"
                cat = now_iso
            else:
                sid = session_state.session_id
                target_proc = getattr(session_state, "target_process", None)
                target_win = getattr(session_state, "target_window", None)
                plane = getattr(session_state.active_plane, "value", str(session_state.active_plane))
                st = status or getattr(session_state.lifecycle_state, "value", str(session_state.lifecycle_state))
                cat = session_state.created_at.isoformat() if hasattr(session_state.created_at, "isoformat") else now_iso

            record = SessionExperienceRecord(
                session_id=sid,
                created_at=cat,
                status=st,
                target_executable=target_proc.executable if target_proc else None,
                target_pid=target_proc.pid if target_proc else None,
                target_hwnd=hex(target_win.hwnd) if target_win and target_win.hwnd else None,
                target_plane=plane,
                scope=ExperienceScope.SESSION,
                metadata=metadata or (getattr(session_state, "diagnostic_state", {}) if not isinstance(session_state, str) else {}),
            )
            return self.store.record_session(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to update session %s: %s", getattr(session_state, "session_id", session_state), e)
            return None

    def on_session_closed(
        self,
        session_state: Any = None,
        *,
        session_id: Optional[str] = None,
        status: str = "CLOSED",
        reason: str = "normal_closure",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[SessionExperienceRecord]:
        """Marks a session record completed with timestamp and closure details."""
        try:
            sid = session_id or (session_state if isinstance(session_state, str) else getattr(session_state, "session_id", None))
            if not sid:
                return None
            now_iso = datetime.now(timezone.utc).isoformat()
            existing = self.store.get_session(sid)
            if existing:
                existing.status = status
                existing.completed_at = now_iso
                existing.metadata["close_reason"] = reason
                if metadata:
                    existing.metadata.update(metadata)
                return self.store.record_session(existing)

            target_proc = getattr(session_state, "target_process", None) if not isinstance(session_state, str) else None
            target_win = getattr(session_state, "target_window", None) if not isinstance(session_state, str) else None

            meta = dict(getattr(session_state, "cleanup_state", {})) if not isinstance(session_state, str) else {}
            meta["close_reason"] = reason
            if metadata:
                meta.update(metadata)

            record = SessionExperienceRecord(
                session_id=sid,
                created_at=now_iso,
                completed_at=now_iso,
                status=status,
                target_executable=target_proc.executable if target_proc else None,
                target_pid=target_proc.pid if target_proc else None,
                target_hwnd=hex(target_win.hwnd) if target_win and target_win.hwnd else None,
                target_plane=getattr(session_state, "active_plane", "NATIVE") if isinstance(session_state, str) else getattr(session_state.active_plane, "value", str(session_state.active_plane)),
                scope=ExperienceScope.SESSION,
                metadata=meta,
            )
            return self.store.record_session(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to close session in experience store: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Mission Integration
    # -------------------------------------------------------------------------

    def on_mission_admitted(
        self,
        mission_or_session: Any = None,
        mission_or_state: Any = None,
        *,
        session_id: Optional[str] = None,
        mission: Optional[Any] = None,
        session_state: Optional[Any] = None,
        **kwargs: Any,
    ) -> Optional[MissionExperienceRecord]:
        """Persists an admitted review mission."""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            m = mission
            if m is None:
                if hasattr(mission_or_session, "mission_id"):
                    m = mission_or_session
                elif hasattr(mission_or_state, "mission_id"):
                    m = mission_or_state

            if m is None:
                return None

            mid = getattr(m, "mission_id", None)
            if not isinstance(mid, str):
                mid = str(mid) if mid is not None else "unknown_mission"

            sid = session_id if isinstance(session_id, str) else None
            if not sid:
                m_sid = getattr(m, "session_id", None)
                if isinstance(m_sid, str):
                    sid = m_sid
                else:
                    sid = "default"

            proj_id = getattr(m, "project_id", None)
            if not isinstance(proj_id, str):
                proj_id = None

            goal = getattr(m, "goal", "")
            if not isinstance(goal, str):
                goal = str(goal) if goal else ""

            scope_val = getattr(m, "scope", ExperienceScope.SESSION)
            if hasattr(scope_val, "value"):
                scope_val = scope_val.value
            if not isinstance(scope_val, str):
                scope_val = str(scope_val)

            meta = dict(getattr(m, "safe_metadata", {}) or {})
            if "max_duration_sec" not in meta:
                max_d = getattr(m, "max_duration_sec", 60)
                meta["max_duration_sec"] = max_d if isinstance(max_d, (int, float)) else 60

            record = MissionExperienceRecord(
                mission_id=mid,
                session_id=sid,
                project_id=proj_id,
                goal=goal,
                scope=scope_val,
                created_at=now_iso,
                status="ADMITTED",
                metadata=meta,
            )
            rec = self.store.record_mission(record)
            self._notify_bridge_mission(mission_id=mid, session_id=sid)
            return rec
        except Exception as e:
            logger.warning("Graceful degradation: failed to persist admitted mission: %s", e)
            return None

    def on_mission_completed(
        self,
        *args: Any,
        mission_or_session: Any = None,
        result_or_mission: Any = None,
        session_state: Optional[Any] = None,
        session_id: Optional[str] = None,
        mission: Optional[Any] = None,
        result: Optional[Any] = None,
        execution_status: Optional[str] = None,
        verdict: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[MissionExperienceRecord]:
        """Updates a review mission record upon completion or cancellation."""
        try:
            now_iso = datetime.now(timezone.utc).isoformat()
            m = mission
            res = result
            st_override = execution_status
            verd_override = verdict
            sid_override = session_id

            if args:
                if len(args) >= 1:
                    if isinstance(args[0], str) and sid_override is None:
                        sid_override = args[0]
                    elif m is None:
                        m = args[0]
                if len(args) >= 2:
                    if m is None and hasattr(args[1], "mission_id"):
                        m = args[1]
                    elif res is None:
                        res = args[1]
                if len(args) >= 3:
                    if st_override is None and isinstance(args[2], str):
                        st_override = args[2]
                    elif res is None:
                        res = args[2]
                if len(args) >= 4:
                    if verd_override is None and isinstance(args[3], str):
                        verd_override = args[3]

            if m is None:
                if hasattr(mission_or_session, "mission_id"):
                    m = mission_or_session
                    res = res or result_or_mission
                elif hasattr(result_or_mission, "mission_id"):
                    m = result_or_mission

            if m is None:
                return None

            session_id = sid_override

            mid = getattr(m, "mission_id", None)
            if not isinstance(mid, str):
                mid = str(mid) if mid is not None else "unknown_mission"

            sid = session_id if isinstance(session_id, str) else None
            if not sid:
                m_sid = getattr(m, "session_id", None)
                if isinstance(m_sid, str):
                    sid = m_sid
                else:
                    sid = "default"

            proj_id = getattr(m, "project_id", None)
            if not isinstance(proj_id, str):
                proj_id = None

            goal = getattr(m, "goal", "")
            if not isinstance(goal, str):
                goal = str(goal) if goal else ""

            scope_val = getattr(m, "scope", ExperienceScope.SESSION)
            if hasattr(scope_val, "value"):
                scope_val = scope_val.value
            if not isinstance(scope_val, str):
                scope_val = str(scope_val)

            final_st = execution_status or (
                getattr(res.final_status, "value", str(res.final_status)) if res and hasattr(res, "final_status") else "COMPLETED"
            )
            if not isinstance(final_st, str):
                final_st = "COMPLETED"

            tech_verdict = verdict or (
                getattr(res, "technical_verdict", "UNVERIFIED") if res and hasattr(res, "technical_verdict") else "UNVERIFIED"
            )
            if not isinstance(tech_verdict, str):
                tech_verdict = "UNVERIFIED"

            meta = dict(getattr(m, "safe_metadata", {}) or {})
            meta.update({
                "verdict": tech_verdict,
                "duration_ms": getattr(res, "duration_ms", 0.0) if (res and isinstance(getattr(res, "duration_ms", None), (int, float))) else 0.0,
                "budget_usage": getattr(res, "budget_usage", {}) if (res and isinstance(getattr(res, "budget_usage", None), dict)) else {},
                "limitations": list(getattr(res, "limitations", [])) if (res and hasattr(res, "limitations") and isinstance(getattr(res, "limitations", None), list)) else [],
            })

            record = MissionExperienceRecord(
                mission_id=mid,
                session_id=sid,
                project_id=proj_id,
                goal=goal,
                scope=scope_val,
                created_at=now_iso,
                completed_at=now_iso,
                status=final_st,
                metadata=meta,
            )
            return self.store.record_mission(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to persist completed mission: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Action Lifecycle Integration
    # -------------------------------------------------------------------------

    def on_action_requested(
        self,
        session_id: str,
        action_request: Any,
    ) -> Optional[ActionReferenceRecord]:
        """Records initial ACTION_REQUESTED milestone reference."""
        try:
            prov = ProvenanceRecord(
                source="ActionExecutionEngine",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_id,
                kind=RecordKind.FACT,
            )
            target_val = getattr(action_request, "reference", getattr(action_request, "target", None))
            target_str = target_val if isinstance(target_val, str) else (str(target_val) if target_val is not None and not hasattr(target_val, "_mock_name") else None)
            params = getattr(action_request, "params", {})
            safe_params = params if isinstance(params, dict) else {}

            record = ActionReferenceRecord(
                action_id=getattr(action_request, "action_id", "act_unknown"),
                session_id=session_id,
                action_type=getattr(getattr(action_request, "action_type", "UNKNOWN"), "value", str(getattr(action_request, "action_type", "UNKNOWN"))),
                plane="UNKNOWN",
                target=target_str,
                status="REQUESTED",
                provenance=prov,
                metadata={"params": safe_params},
            )
            return self.store.record_action_reference(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to record action requested %s: %s", getattr(action_request, "action_id", "unknown"), e)
            return None

    def on_action_dispatched(
        self,
        session_id: str,
        action_request: Any,
        receipt: Any,
    ) -> Optional[ActionReferenceRecord]:
        """Records ACTION_DISPATCHED receipt reference."""
        try:
            prov = ProvenanceRecord(
                source="ActionExecutionEngine",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_id,
                kind=RecordKind.FACT,
            )
            target_val = getattr(receipt, "reference", getattr(receipt, "target", None))
            if not isinstance(target_val, str):
                target_val = getattr(action_request, "reference", getattr(action_request, "target", None))
            target_str = target_val if isinstance(target_val, str) else (str(target_val) if target_val is not None and not hasattr(target_val, "_mock_name") else None)
            dur = getattr(receipt, "duration_ms", None)
            dur_ms = float(dur) if isinstance(dur, (int, float)) else None

            record = ActionReferenceRecord(
                action_id=getattr(action_request, "action_id", "act_unknown"),
                session_id=session_id,
                action_type=getattr(getattr(action_request, "action_type", "UNKNOWN"), "value", str(getattr(action_request, "action_type", "UNKNOWN"))),
                plane=getattr(getattr(receipt, "plane", "NATIVE"), "value", str(getattr(receipt, "plane", "NATIVE"))),
                target=target_str,
                status=getattr(getattr(receipt, "dispatch_status", "DISPATCHED"), "value", str(getattr(receipt, "dispatch_status", "DISPATCHED"))),
                duration_ms=dur_ms,
                provenance=prov,
                metadata={
                    "dispatch_method": getattr(getattr(receipt, "dispatch_method", "DEFAULT"), "value", str(getattr(receipt, "dispatch_method", "DEFAULT"))),
                    "error": getattr(receipt, "error", None) if isinstance(getattr(receipt, "error", None), str) else None,
                },
            )
            return self.store.record_action_reference(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to record action dispatched %s: %s", getattr(action_request, "action_id", "unknown"), e)
            return None

    def on_action_settled(
        self,
        session_id: str,
        action_request: Any,
        receipt: Any,
        outcome: Any,
        trace_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
    ) -> Optional[ActionReferenceRecord]:
        """Records ACTION_SETTLED outcome reference with duration and correlation links."""
        try:
            ev_id = evidence_id or (getattr(outcome.manifest, "manifest_id", None) if getattr(outcome, "manifest", None) else None)
            prov = ProvenanceRecord(
                source="ActionExecutionEngine",
                source_type=RecordSourceType.RUNTIME,
                session_id=session_id,
                trace_reference=trace_id,
                evidence_reference=ev_id if isinstance(ev_id, str) else None,
                kind=RecordKind.FACT,
            )
            st = "SETTLED" if getattr(outcome, "verdict", None) else getattr(getattr(outcome, "outcome_status", "SETTLED"), "value", str(getattr(outcome, "outcome_status", "SETTLED")))
            target_val = getattr(receipt, "reference", getattr(receipt, "target", None))
            if not isinstance(target_val, str):
                target_val = getattr(action_request, "reference", getattr(action_request, "target", None))
            target_str = target_val if isinstance(target_val, str) else (str(target_val) if target_val is not None and not hasattr(target_val, "_mock_name") else None)
            dur = getattr(outcome, "duration_ms", None)
            dur_ms = float(dur) if isinstance(dur, (int, float)) else None

            record = ActionReferenceRecord(
                action_id=getattr(action_request, "action_id", "act_unknown"),
                session_id=session_id,
                action_type=getattr(getattr(action_request, "action_type", "UNKNOWN"), "value", str(getattr(action_request, "action_type", "UNKNOWN"))),
                plane=getattr(getattr(receipt, "plane", "NATIVE"), "value", str(getattr(receipt, "plane", "NATIVE"))),
                target=target_str,
                status=st,
                duration_ms=dur_ms,
                provenance=prov,
                metadata={
                    "state_change": getattr(getattr(outcome, "state_change", None), "value", str(getattr(outcome, "state_change", ""))),
                    "pre_epoch": getattr(outcome, "pre_epoch", 0) if isinstance(getattr(outcome, "pre_epoch", None), int) else 0,
                    "post_epoch": getattr(outcome, "post_epoch", 0) if isinstance(getattr(outcome, "post_epoch", None), int) else 0,
                    "verdict": getattr(outcome, "verdict", None) if isinstance(getattr(outcome, "verdict", None), str) else None,
                },
            )
            rec = self.store.record_action_reference(record)
            self._notify_bridge_action(
                action_id=record.action_id,
                session_id=record.session_id,
                duration_ms=record.duration_ms,
                action_type=record.action_type,
            )
            return rec
        except Exception as e:
            logger.warning("Graceful degradation: failed to record action settled %s: %s", getattr(action_request, "action_id", "unknown"), e)
            return None

    # -------------------------------------------------------------------------
    # Trace & Observability Integration
    # -------------------------------------------------------------------------

    def on_trace_event(self, event: DesktopTraceEvent) -> Optional[TraceReferenceRecord]:
        """
        Selectively persists significant trace events into durable trace references.
        Prevents unbounded trace spam while capturing key physical and review milestones.
        """
        et = getattr(event, "event_type", None)
        et_name = getattr(et, "value", str(et)) if et else ""
        if et not in SIGNIFICANT_TRACE_EVENTS and et_name not in SIGNIFICANT_TRACE_EVENT_NAMES:
            return None

        try:
            corr = getattr(event, "correlation", None)
            sid = getattr(corr, "session_id", None) if corr else None
            if not isinstance(sid, str):
                sid = "default_session"
            mid = getattr(corr, "mission_id", None) if corr else None
            act_id = getattr(corr, "action_id", None) if corr else None

            prov = ProvenanceRecord(
                source="DesktopTraceEngine",
                source_type=RecordSourceType.TRACE_ENGINE,
                session_id=sid,
                mission_id=mid if isinstance(mid, str) else None,
                confidence=1.0,
                kind=RecordKind.FACT,
                timestamp=getattr(event, "timestamp", time.time()) if isinstance(getattr(event, "timestamp", None), (int, float)) else time.time(),
            )
            # Store bounded metadata without large payloads
            meta = {
                "action_id": act_id if isinstance(act_id, str) else None,
                "status": getattr(event, "status", "SUCCESS") if isinstance(getattr(event, "status", None), str) else "SUCCESS",
                "duration_ms": getattr(event, "duration_ms", 0.0) if isinstance(getattr(event, "duration_ms", None), (int, float)) else 0.0,
                "plane": getattr(getattr(event, "plane", "NATIVE"), "value", str(getattr(event, "plane", "NATIVE"))),
            }
            if getattr(event, "details", None) and isinstance(event.details, dict):
                # Include shallow scalar details only
                for k, v in event.details.items():
                    if isinstance(v, (str, int, float, bool)) and len(str(v)) <= 200:
                        meta[k] = v

            record = TraceReferenceRecord(
                event_id=getattr(event, "event_id", f"trace_{time.time()}"),
                session_id=sid,
                sequence_monotonic=getattr(event, "sequence_monotonic", 0) if isinstance(getattr(event, "sequence_monotonic", None), int) else 0,
                event_type=et_name,
                plane=getattr(getattr(event, "plane", "NATIVE"), "value", str(getattr(event, "plane", "NATIVE"))),
                provenance=prov,
                metadata=meta,
            )
            return self.store.record_trace_reference(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to record trace reference %s: %s", getattr(event, "event_id", "unknown"), e)
            return None

    # -------------------------------------------------------------------------
    # Forensic Evidence Integration
    # -------------------------------------------------------------------------

    def on_evidence_created(
        self,
        session_id: str,
        artifact_or_action_id: Any = None,
        artifact: Any = None,
        *,
        action_id: Optional[str] = None,
        evidence_id: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[EvidenceReferenceRecord]:
        """
        Records an evidence reference pointing to an authoritative forensic artifact.
        NEVER stores screenshot byte blobs in SQLite; persists paths, hashes, and IDs only.
        """
        try:
            art = artifact
            act_id = action_id
            if art is None:
                if hasattr(artifact_or_action_id, "artifact_id") or hasattr(artifact_or_action_id, "sha256") or hasattr(artifact_or_action_id, "mime_type"):
                    art = artifact_or_action_id
                else:
                    art = kwargs.get("artifact")
                    if isinstance(artifact_or_action_id, str):
                        act_id = act_id or artifact_or_action_id
            else:
                if isinstance(artifact_or_action_id, str):
                    act_id = act_id or artifact_or_action_id

            if art is None:
                return None

            e_id = evidence_id or f"ev_ref_{getattr(art, 'artifact_id', 'unknown')}"
            prov = ProvenanceRecord(
                source="EvidenceStore",
                source_type=RecordSourceType.EVIDENCE_STORE,
                session_id=session_id,
                evidence_reference=e_id,
                kind=RecordKind.FACT,
            )
            record = EvidenceReferenceRecord(
                evidence_id=e_id,
                session_id=session_id,
                action_id=act_id,
                artifact_id=getattr(art, "artifact_id", "unknown"),
                artifact_type=getattr(art, "mime_type", "application/octet-stream"),
                checksum_sha256=getattr(art, "sha256", ""),
                relative_path_or_uri=getattr(art, "relative_path", str(art)),
                provenance=prov,
                metadata={"size_bytes": getattr(art, "size_bytes", 0) if isinstance(getattr(art, "size_bytes", None), (int, float)) else 0},
            )
            return self.store.record_evidence_reference(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to record evidence reference: %s", e)
            return None

    # -------------------------------------------------------------------------
    # Verification & Verdict Integration
    # -------------------------------------------------------------------------

    def on_verification_completed(
        self,
        session_id: str,
        manifest: Any = None,
        action_id: Optional[str] = None,
        verdict: Optional[Any] = None,
        confidence: Optional[float] = None,
        **kwargs: Any,
    ) -> Optional[OutcomeRecord]:
        """
        Persists authoritative verification results.
        Strictly preserves the tripartite PASS / FAIL / UNVERIFIED discipline.
        """
        try:
            if isinstance(manifest, str) and action_id is not None and not isinstance(action_id, str):
                actual_action_id = manifest
                actual_verdict = action_id
                actual_manifest = verdict
                actual_conf = confidence if confidence is not None else 1.0
            elif isinstance(manifest, str) and verdict is not None:
                actual_action_id = manifest
                actual_verdict = verdict
                actual_manifest = kwargs.get("manifest")
                actual_conf = confidence if confidence is not None else 1.0
            else:
                actual_manifest = manifest or kwargs.get("manifest")
                actual_action_id = action_id or getattr(actual_manifest, "action_id", f"act_{uuid.uuid4().hex[:6]}")
                actual_verdict = verdict or getattr(actual_manifest, "verdict", "UNVERIFIED")
                actual_conf = confidence if confidence is not None else getattr(actual_manifest, "confidence", 1.0)

            v_str = getattr(actual_verdict, "value", str(actual_verdict)).upper()
            m_id = getattr(actual_manifest, "manifest_id", f"man_{actual_action_id}")
            err_cat = None

            # Capture failure / unverified classification
            uv_reasons = getattr(actual_manifest, "unverified_reasons", [])
            if uv_reasons:
                err_cat = str(uv_reasons[0])

            prov = ProvenanceRecord(
                source="VerificationEngine",
                source_type=RecordSourceType.USER_VERIFICATION,
                session_id=session_id,
                confidence=actual_conf,
                evidence_reference=m_id,
                kind=RecordKind.FACT,
            )
            record = OutcomeRecord(
                outcome_id=f"out_{actual_action_id}",
                session_id=session_id,
                verdict=v_str,
                confidence=actual_conf,
                provenance=prov,
                error_category=err_cat,
                details={
                    "action_id": actual_action_id,
                    "manifest_id": m_id,
                    "proof_level": getattr(getattr(actual_manifest, "proof_level", None), "value", None),
                    "claims_count": len(getattr(actual_manifest, "claims", [])),
                },
            )
            return self.store.record_outcome(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to record outcome for action %s: %s", action_id, e)
            return None

    # -------------------------------------------------------------------------
    # Failure Normalization & Recovery Integration
    # -------------------------------------------------------------------------

    def on_failure_diagnosed(
        self,
        session_id: str,
        failure_source: Any = None,
        action_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        action_type: Optional[str] = None,
        plane: Optional[str] = None,
        target_role_or_class: Optional[str] = None,
        verification_verdict: Optional[str] = None,
        recovery_result: Optional[str] = None,
        recovery_reference: Optional[str] = None,
        trace_reference: Optional[str] = None,
        evidence_reference: Optional[str] = None,
        raw_context: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Optional[NormalizedFailureRecord]:
        """
        Normalizes runtime failures into stable categories and deterministic signatures.
        Persists failure intelligence for historical cross-session querying.
        """
        try:
            src = failure_source or kwargs.get("error")
            req = kwargs.get("action_request")
            rec = kwargs.get("action_receipt")
            out = kwargs.get("outcome")

            act_type = action_type or (getattr(req.action_type, "value", str(req.action_type)) if req else None)
            pln = plane or (getattr(rec.plane, "value", str(rec.plane)) if rec else None)
            v_verdict = verification_verdict or (getattr(out, "verdict", None) if out else None)

            record = FailureNormalizer.create_failure_record(
                session_id=session_id,
                failure_source=src,
                action_id=action_id,
                mission_id=mission_id,
                action_type=act_type,
                plane=pln,
                target_role_or_class=target_role_or_class,
                verification_verdict=v_verdict,
                recovery_result=recovery_result,
                recovery_reference=recovery_reference,
                trace_reference=trace_reference,
                evidence_reference=evidence_reference,
                raw_context=raw_context or kwargs,
            )
            return self.store.record_failure(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to normalize/record failure for %s: %s", session_id, e)
            return None

    def on_recovery_completed(
        self,
        session_id: str,
        attempt_record: Any = None,
        action_id: Optional[str] = None,
        mission_id: Optional[str] = None,
        recovery_record: Any = None,
        **kwargs: Any,
    ) -> Optional[RecoveryExperienceRecord]:
        """Persists a bounded recovery attempt record into durable experience storage."""
        rec = recovery_record if recovery_record is not None else attempt_record
        if rec is None:
            return None
        try:
            prov = ProvenanceRecord(
                source="RecoveryEngine",
                source_type=RecordSourceType.DIAGNOSTICS,
                session_id=session_id,
                mission_id=mission_id,
                kind=RecordKind.FACT,
            )
            cat_val = getattr(getattr(rec, "trigger_category", None), "value", str(getattr(rec, "trigger_category", "UNKNOWN")))
            act_val = getattr(getattr(rec, "action", None), "value", str(getattr(rec, "action", "UNKNOWN")))

            record = RecoveryExperienceRecord(
                recovery_id=getattr(rec, "recovery_id", f"rec_{time.time()}"),
                session_id=session_id,
                failure_category=cat_val,
                recovery_action=act_val,
                attempt_number=getattr(rec, "attempt_number", 1),
                max_attempts=getattr(rec, "max_attempts", 1),
                result=getattr(rec, "result", "UNKNOWN"),
                duration_ms=getattr(rec, "duration_ms", 0.0),
                provenance=prov,
                action_id=action_id,
                failure_id=getattr(rec, "failure_id", None),
                error=getattr(rec, "error", None),
                evidence_refs=list(getattr(rec, "evidence_refs", [])),
                trace_event_id=getattr(rec, "trace_event_id", None),
                timestamp=getattr(rec, "started_at", time.time()),
                metadata={},
            )
            return self.store.record_recovery_attempt(record)
        except Exception as e:
            logger.warning("Graceful degradation: failed to record recovery attempt %s: %s", getattr(rec, "recovery_id", "unknown"), e)
            return None
