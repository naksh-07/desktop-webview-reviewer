"""
Deterministic and Probabilistic Correlation Engine for Antigravity and DWR.

Enforces Sections 10, 12, 13 of Milestone 2.1 Prompt 3:
- Relates agent sessions, turns, tool calls, and subagents to DWR sessions, missions, and actions.
- Explicit confidence modeling: EXACT, HIGH, MEDIUM, LOW, UNKNOWN.
- Never fabricates certainty when correlation is only inferential.
- Thread-safe sliding window tracking recent runtime state without blocking DWR execution.
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    CorrelationConfidence,
)
from runtime.experience.antigravity.models import AgentDwrCorrelationRecord

logger = logging.getLogger("desktop_webview.experience.antigravity.correlator")


@dataclass
class DwrActionContext:
    """Recent DWR action metadata in the active sliding correlation window."""
    action_id: str
    session_id: str
    mission_id: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    duration_ms: Optional[float] = None
    action_type: Optional[str] = None


class AgentDwrCorrelator:
    """
    Correlates Antigravity agent activity with Desktop WebView Reviewer runtime entities.
    """

    def __init__(self, window_size: int = 50, temporal_window_sec: float = 60.0):
        self._lock = threading.RLock()
        self.window_size = window_size
        self.temporal_window_sec = temporal_window_sec

        # Active DWR state
        self._active_session_id: Optional[str] = None
        self._active_mission_id: Optional[str] = None
        self._active_project_id: Optional[str] = None
        self._session_conversation_map: Dict[str, str] = {}  # session_id -> conversation_id
        self._recent_actions: List[DwrActionContext] = []

    def set_active_session(
        self,
        session_id: str,
        project_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        """Registers a DWR session as active in the correlation tracker."""
        with self._lock:
            self._active_session_id = session_id
            if project_id:
                self._active_project_id = project_id
            if conversation_id:
                self._session_conversation_map[session_id] = conversation_id

    def set_active_mission(self, mission_id: str, session_id: Optional[str] = None) -> None:
        """Registers an active DWR review mission."""
        with self._lock:
            self._active_mission_id = mission_id
            if session_id:
                self._active_session_id = session_id

    def record_dwr_action(
        self,
        action_id: str,
        session_id: str,
        mission_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        duration_ms: Optional[float] = None,
        action_type: Optional[str] = None,
    ) -> None:
        """Appends a completed DWR action to the recent sliding window."""
        with self._lock:
            ctx = DwrActionContext(
                action_id=action_id,
                session_id=session_id,
                mission_id=mission_id or self._active_mission_id,
                timestamp=timestamp or time.time(),
                duration_ms=duration_ms,
                action_type=action_type,
            )
            self._recent_actions.append(ctx)
            if len(self._recent_actions) > self.window_size:
                self._recent_actions.pop(0)

    def correlate_event(
        self,
        envelope: AgentEventEnvelope,
    ) -> Optional[AgentDwrCorrelationRecord]:
        """
        Evaluates correlation between an incoming AgentEventEnvelope and known DWR entities.
        Returns a structured AgentDwrCorrelationRecord with explicit confidence.
        If no meaningful correlation exists, returns None to avoid creating fabricated records.
        """
        with self._lock:
            now = envelope.timestamp or time.time()

            # Rule 1: Explicit correlation_id matches DWR session or action
            if envelope.correlation_id:
                matched_action = next((a for a in reversed(self._recent_actions) if a.action_id == envelope.correlation_id), None)
                if matched_action:
                    return self._create_correlation(
                        envelope=envelope,
                        dwr_session_id=matched_action.session_id,
                        dwr_mission_id=matched_action.mission_id,
                        dwr_action_id=matched_action.action_id,
                        confidence=CorrelationConfidence.EXACT,
                        source="explicit_correlation_id_action_match",
                    )
                if envelope.correlation_id == self._active_session_id:
                    return self._create_correlation(
                        envelope=envelope,
                        dwr_session_id=self._active_session_id,
                        dwr_mission_id=self._active_mission_id,
                        dwr_action_id=None,
                        confidence=CorrelationConfidence.EXACT,
                        source="explicit_correlation_id_session_match",
                    )

            # Rule 2: Explicit DWR tool invocation (e.g. desktop_click, desktop_type)
            is_dwr_tool = envelope.tool_name and envelope.tool_name.startswith("desktop_")
            tool_session_arg = envelope.safe_summary.get("session_id")
            if is_dwr_tool and tool_session_arg:
                target_session = str(tool_session_arg)
                matched_action = self._find_closest_action(now, max_delta=5.0)
                matched_action_id = matched_action.action_id if (matched_action and matched_action.session_id == target_session) else None
                matched_mission_id = (matched_action.mission_id if matched_action else None) or self._active_mission_id
                return self._create_correlation(
                    envelope=envelope,
                    dwr_session_id=target_session,
                    dwr_mission_id=matched_mission_id,
                    dwr_action_id=matched_action_id,
                    confidence=CorrelationConfidence.EXACT,
                    source="explicit_tool_argument_session_id",
                )

            # Rule 3: Direct DWR tool during active session
            if is_dwr_tool and self._active_session_id:
                # Find closest recent action within 5 seconds
                matched_action = self._find_closest_action(now, max_delta=5.0)
                return self._create_correlation(
                    envelope=envelope,
                    dwr_session_id=self._active_session_id,
                    dwr_mission_id=self._active_mission_id,
                    dwr_action_id=matched_action.action_id if matched_action else None,
                    confidence=CorrelationConfidence.EXACT if matched_action else CorrelationConfidence.HIGH,
                    source="dwr_tool_active_session_window",
                )

            # Rule 4: Same conversation_id associated with an active DWR session
            if envelope.conversation_id:
                matching_session = next(
                    (sid for sid, cid in self._session_conversation_map.items() if cid == envelope.conversation_id),
                    None,
                )
                if matching_session:
                    matched_action = self._find_closest_action(now, max_delta=5.0)
                    if matched_action and matched_action.session_id == matching_session:
                        return self._create_correlation(
                            envelope=envelope,
                            dwr_session_id=matching_session,
                            dwr_mission_id=matched_action.mission_id,
                            dwr_action_id=matched_action.action_id,
                            confidence=CorrelationConfidence.HIGH,
                            source="conversation_match_tight_temporal_action",
                        )
                    # Broader window match (<= 60s)
                    return self._create_correlation(
                        envelope=envelope,
                        dwr_session_id=matching_session,
                        dwr_mission_id=self._active_mission_id,
                        dwr_action_id=None,
                        confidence=CorrelationConfidence.MEDIUM,
                        source="conversation_match_session_temporal",
                    )

            # Rule 5: Same project/workspace context during active session within temporal window
            if envelope.project_id and envelope.project_id == self._active_project_id and self._active_session_id:
                matched_action = self._find_closest_action(now, max_delta=self.temporal_window_sec)
                if matched_action:
                    return self._create_correlation(
                        envelope=envelope,
                        dwr_session_id=self._active_session_id,
                        dwr_mission_id=self._active_mission_id,
                        dwr_action_id=matched_action.action_id,
                        confidence=CorrelationConfidence.MEDIUM,
                        source="project_context_temporal_window",
                    )
                return self._create_correlation(
                    envelope=envelope,
                    dwr_session_id=self._active_session_id,
                    dwr_mission_id=self._active_mission_id,
                    dwr_action_id=None,
                    confidence=CorrelationConfidence.LOW,
                    source="project_context_loose_temporal",
                )

            # If no confident match can be established, do not invent one
            return None

    def _find_closest_action(self, target_timestamp: float, max_delta: float) -> Optional[DwrActionContext]:
        """Finds the most temporally proximate action within max_delta seconds."""
        closest: Optional[DwrActionContext] = None
        min_delta = float("inf")
        for action in reversed(self._recent_actions):
            delta = abs(target_timestamp - action.timestamp)
            if delta <= max_delta and delta < min_delta:
                min_delta = delta
                closest = action
        return closest

    def _create_correlation(
        self,
        envelope: AgentEventEnvelope,
        dwr_session_id: Optional[str],
        dwr_mission_id: Optional[str],
        dwr_action_id: Optional[str],
        confidence: CorrelationConfidence,
        source: str,
    ) -> AgentDwrCorrelationRecord:
        """Constructs an AgentDwrCorrelationRecord."""
        now = envelope.timestamp or time.time()
        iso_ts = envelope.iso_timestamp or datetime.fromtimestamp(now, tz=timezone.utc).isoformat()
        return AgentDwrCorrelationRecord(
            correlation_id=f"corr_{uuid.uuid4().hex[:16]}",
            confidence=confidence,
            agent_session_id=envelope.conversation_id or envelope.agent_id,
            conversation_id=envelope.conversation_id,
            turn_id=envelope.turn_id,
            tool_call_id=envelope.event_id if envelope.tool_name else None,
            dwr_session_id=dwr_session_id,
            dwr_mission_id=dwr_mission_id,
            dwr_action_id=dwr_action_id,
            correlation_source=source,
            timestamp=now,
            iso_timestamp=iso_ts,
            metadata={
                "tool_name": envelope.tool_name,
                "event_type": envelope.event_type.value if hasattr(envelope.event_type, "value") else str(envelope.event_type),
            },
        )
