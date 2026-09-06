"""
Antigravity Correlation Bridge (Milestone 2.1 Prompt 3).

Central coordination hub between Antigravity agent events and the Desktop WebView Reviewer
Experience Store.

Enforces:
- Standalone operation: DWR functions normally if Antigravity is absent, disabled, or misconfigured.
- Fail-safe design: persistence or correlation errors never crash or block live desktop review.
- Privacy-first zero-knowledge boundary: strips model reasoning, transcripts, and credentials.
- Multi-dimensional correlation: explicit confidence metrics linking agent activity with DWR reality.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Union

from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    AgentEventType,
    CorrelationConfidence,
    UserCorrectionType,
)
from runtime.experience.antigravity.correlator import AgentDwrCorrelator
from runtime.experience.antigravity.hook_adapter import AntigravityHookAdapter
from runtime.experience.antigravity.models import (
    AgentArtifactRecord,
    AgentCorrectionRecord,
    AgentDwrCorrelationRecord,
    AgentSessionRecord,
    AgentSubagentRecord,
    AgentToolCallRecord,
    AgentTurnRecord,
    AntigravityBridgeStatus,
)
from runtime.experience.antigravity.sanitizer import AgentEventSanitizer

logger = logging.getLogger("desktop_webview.experience.antigravity.bridge")

ENV_ANTIGRAVITY_BRIDGE_ENABLED = "DESKTOP_REVIEWER_ANTIGRAVITY_BRIDGE_ENABLED"


class AntigravityCorrelationBridge:
    """
    Coordinator connecting Antigravity agent lifecycle events to DWR experience storage.
    """

    _default_bridge: Optional[AntigravityCorrelationBridge] = None
    _bridge_lock: threading.Lock = threading.Lock()

    def __init__(
        self,
        store: Optional[Any] = None,
        sanitizer: Optional[AgentEventSanitizer] = None,
        correlator: Optional[AgentDwrCorrelator] = None,
        enabled: bool = True,
    ):
        self._lock = threading.RLock()
        self._store = store
        self.sanitizer = sanitizer or AgentEventSanitizer(fail_safe=True)
        self.correlator = correlator or AgentDwrCorrelator()
        self.hook_adapter = AntigravityHookAdapter(sanitizer=self.sanitizer)

        # Check environment flag override (defaults to True)
        env_val = os.environ.get(ENV_ANTIGRAVITY_BRIDGE_ENABLED, "true").strip().lower()
        self.enabled = enabled and (env_val not in ("false", "0", "no", "disabled"))

        self._last_event_timestamp: Optional[str] = None
        self._correlation_count: int = 0

    @classmethod
    def get_default_bridge(cls) -> AntigravityCorrelationBridge:
        """Singleton accessor for the default correlation bridge."""
        with cls._bridge_lock:
            if cls._default_bridge is None:
                cls._default_bridge = cls()
            return cls._default_bridge

    @property
    def store(self) -> Optional[Any]:
        """Lazy access to ExperienceStore to avoid circular imports."""
        if self._store is None:
            try:
                from runtime.experience.store import ExperienceStore
                self._store = ExperienceStore.get_default_store()
            except Exception as e:
                logger.debug("ExperienceStore not available for bridge: %s", e)
        return self._store

    def ingest_raw_hook(
        self,
        hook_name: str,
        payload: Dict[str, Any],
    ) -> Optional[AgentDwrCorrelationRecord]:
        """Translates a raw hook payload and ingests it into the bridge."""
        if not self.enabled:
            return None
        try:
            envelope = self.hook_adapter.translate_hook(hook_name, payload)
            if envelope:
                return self.ingest_event(envelope)
        except Exception as e:
            logger.warning("Failed to ingest raw hook '%s': %s", hook_name, e)
        return None

    def ingest_event(
        self,
        envelope: AgentEventEnvelope,
    ) -> Optional[AgentDwrCorrelationRecord]:
        """
        Main entry point for incoming AgentEventEnvelopes.
        1. Sanitizes the envelope defensively.
        2. Dispatches structured record to Experience Store.
        3. Computes correlation with active DWR context.
        4. Persists correlation record if established.
        """
        if not self.enabled:
            return None

        with self._lock:
            try:
                # 1. Sanitize
                clean_env = self.sanitizer.sanitize_envelope(envelope)
                if not clean_env:
                    return None

                self._last_event_timestamp = clean_env.iso_timestamp

                # 2. Persist specific entity records to Experience Store
                st = self.store
                if st is not None:
                    self._persist_entity_record(st, clean_env)

                # 3. Compute correlation with DWR
                correlation = self.correlator.correlate_event(clean_env)
                if correlation:
                    self._correlation_count += 1
                    if st is not None and hasattr(st, "record_agent_correlation"):
                        st.record_agent_correlation(correlation)

                return correlation

            except Exception as e:
                logger.warning("Error ingesting agent event in bridge: %s", e)
                return None

    def _persist_entity_record(self, st: Any, env: AgentEventEnvelope) -> None:
        """Helper to persist corresponding normalized agent records based on event type."""
        try:
            # Session lifecycle
            if env.event_type in (AgentEventType.AGENT_SESSION_STARTED, AgentEventType.AGENT_SESSION_COMPLETED):
                if hasattr(st, "record_agent_session"):
                    sid = env.conversation_id or env.agent_id or f"asess_{env.event_id}"
                    st.record_agent_session(
                        AgentSessionRecord(
                            agent_session_id=sid,
                            conversation_id=env.conversation_id or sid,
                            agent_id=env.agent_id,
                            workspace_id=env.workspace_id,
                            started_at=env.iso_timestamp,
                            completed_at=env.iso_timestamp if env.event_type == AgentEventType.AGENT_SESSION_COMPLETED else None,
                            status="COMPLETED" if env.event_type == AgentEventType.AGENT_SESSION_COMPLETED else "ACTIVE",
                            metadata=env.safe_summary,
                        )
                    )

            # Turn lifecycle
            elif env.event_type in (AgentEventType.AGENT_TURN_STARTED, AgentEventType.AGENT_TURN_COMPLETED):
                if hasattr(st, "record_agent_turn"):
                    st.record_agent_turn(
                        AgentTurnRecord(
                            turn_id=env.turn_id or f"aturn_{env.event_id}",
                            agent_session_id=env.conversation_id or env.agent_id or "default_session",
                            conversation_id=env.conversation_id,
                            step_index=env.safe_summary.get("step_index"),
                            timestamp=env.timestamp,
                            iso_timestamp=env.iso_timestamp,
                            status="COMPLETED" if env.event_type == AgentEventType.AGENT_TURN_COMPLETED else "STARTED",
                            metadata=env.safe_summary,
                        )
                    )

            # Tool execution
            elif env.event_type in (AgentEventType.AGENT_TOOL_STARTED, AgentEventType.AGENT_TOOL_COMPLETED, AgentEventType.AGENT_TOOL_FAILED):
                if hasattr(st, "record_agent_tool_call"):
                    st.record_agent_tool_call(
                        AgentToolCallRecord(
                            tool_call_id=env.event_id,
                            turn_id=env.turn_id,
                            agent_session_id=env.conversation_id or env.agent_id,
                            conversation_id=env.conversation_id,
                            tool_name=env.tool_name or "unknown",
                            tool_category=env.tool_category or "generic",
                            success=env.success if env.success is not None else (env.event_type != AgentEventType.AGENT_TOOL_FAILED),
                            error_class=env.error_class,
                            duration_ms=env.duration_ms,
                            timestamp=env.timestamp,
                            iso_timestamp=env.iso_timestamp,
                            safe_summary=env.safe_summary,
                        )
                    )

            # Subagent delegation
            elif env.event_type in (AgentEventType.AGENT_SUBAGENT_STARTED, AgentEventType.AGENT_SUBAGENT_COMPLETED, AgentEventType.AGENT_SUBAGENT_FAILED):
                if hasattr(st, "record_agent_subagent"):
                    st.record_agent_subagent(
                        AgentSubagentRecord(
                            subagent_id=env.subagent_id or f"sub_{env.event_id}",
                            parent_agent_id=env.parent_agent_id,
                            conversation_id=env.conversation_id,
                            agent_session_id=env.conversation_id or env.agent_id,
                            status="COMPLETED" if env.event_type == AgentEventType.AGENT_SUBAGENT_COMPLETED else ("FAILED" if env.event_type == AgentEventType.AGENT_SUBAGENT_FAILED else "RUNNING"),
                            created_at=env.iso_timestamp,
                            completed_at=env.iso_timestamp if env.event_type != AgentEventType.AGENT_SUBAGENT_STARTED else None,
                            metadata=env.safe_summary,
                        )
                    )

            # Artifact reference
            elif env.event_type == AgentEventType.AGENT_ARTIFACT_CREATED:
                if hasattr(st, "record_agent_artifact") and env.artifact_reference:
                    art_id = env.safe_summary.get("artifact_id") or f"art_{env.event_id}"
                    art_type = env.safe_summary.get("artifact_type") or "file"
                    st.record_agent_artifact(
                        AgentArtifactRecord(
                            artifact_id=art_id,
                            artifact_type=art_type,
                            safe_reference=env.artifact_reference,
                            agent_session_id=env.conversation_id or env.agent_id,
                            turn_id=env.turn_id,
                            timestamp=env.timestamp,
                            iso_timestamp=env.iso_timestamp,
                            metadata=env.safe_summary,
                        )
                    )

            # Corrections
            elif env.event_type in (AgentEventType.AGENT_CORRECTION, AgentEventType.AGENT_USER_CORRECTION):
                if hasattr(st, "record_agent_correction"):
                    st.record_agent_correction(
                        AgentCorrectionRecord(
                            correction_id=f"corr_{env.event_id}",
                            correction_type=env.safe_summary.get("correction_type", UserCorrectionType.USER_CORRECTED_AGENT.value),
                            agent_session_id=env.conversation_id or env.agent_id,
                            conversation_id=env.conversation_id,
                            turn_id=env.turn_id,
                            related_dwr_session_id=env.correlation_id,
                            timestamp=env.timestamp,
                            iso_timestamp=env.iso_timestamp,
                            classification_details=env.safe_summary,
                        )
                    )
        except Exception as e:
            logger.debug("Failed to persist entity record in store: %s", e)

    # -------------------------------------------------------------------------
    # DWR Runtime Observation Hooks
    # -------------------------------------------------------------------------

    def on_dwr_session_started(
        self,
        session_id: str,
        project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Called when a DWR review session initializes."""
        if not self.enabled:
            return
        self.correlator.set_active_session(session_id, project_id=project_id, conversation_id=conversation_id)

    def on_dwr_mission_admitted(self, mission_id: str, session_id: str) -> None:
        """Called when a DWR mission is admitted."""
        if not self.enabled:
            return
        self.correlator.set_active_mission(mission_id, session_id=session_id)

    def on_dwr_action_settled(
        self,
        action_id: str,
        session_id: str,
        mission_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        duration_ms: Optional[float] = None,
        action_type: Optional[str] = None,
    ) -> None:
        """Called when a physical or web action settles."""
        if not self.enabled:
            return
        self.correlator.record_dwr_action(
            action_id=action_id,
            session_id=session_id,
            mission_id=mission_id,
            timestamp=timestamp,
            duration_ms=duration_ms,
            action_type=action_type,
        )

    # -------------------------------------------------------------------------
    # Diagnostics & Status
    # -------------------------------------------------------------------------

    def get_status(self) -> AntigravityBridgeStatus:
        """Provides a safe diagnostic report for CLI Doctor and MCP passive resources."""
        return AntigravityBridgeStatus(
            installed_or_configured=True,
            enabled=self.enabled,
            last_event_timestamp=self._last_event_timestamp,
            events_accepted=self.sanitizer.events_accepted,
            events_rejected=self.sanitizer.events_rejected,
            correlation_records=self._correlation_count,
            privacy_violations_blocked=self.sanitizer.privacy_violations_blocked,
        )
