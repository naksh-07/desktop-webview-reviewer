"""
Antigravity Host Integration Adapter (Architecture H / Phase 18).
Provides a thin, decoupled host-facing boundary between Antigravity (controlling agent)
and the Reviewer 2.0 autonomous mission runtime.
The core Reviewer remains independently executable without hard-coded dependencies.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional, Callable, Any

from runtime.mission_models import (
    ReviewMission,
    AdmissionResult,
    ReviewMissionResult,
    MissionLifecycleState,
)
from runtime.mission_orchestrator import ReviewMissionOrchestrator
from runtime.observation_security import sanitize_observed_text, create_safe_ui_envelope

logger = logging.getLogger("desktop_webview.antigravity_adapter")


class AntigravityReviewerAdapter:
    """
    Host-facing integration adapter for Antigravity.
    Translates controlling-agent mission requests into Reviewer authority envelopes,
    streams execution progress, and enforces untrusted data boundaries.
    """

    def __init__(self, orchestrator: Optional[ReviewMissionOrchestrator] = None):
        self.orchestrator = orchestrator or ReviewMissionOrchestrator()
        self._listeners: List[Callable[[str, Dict[str, Any]], None]] = []

    def add_listener(self, callback: Callable[[str, Dict[str, Any]], None]) -> None:
        """Subscribes an event listener for outgoing mission lifecycle notifications."""
        self._listeners.append(callback)

    def _notify(self, event_type: str, payload: Dict[str, Any]) -> None:
        """Dispatches an outgoing notification to all registered listeners."""
        for listener in self._listeners:
            try:
                listener(event_type, payload)
            except Exception as e:
                logger.debug(f"Listener notification error for {event_type}: {e}")

    def submit_mission(
        self,
        mission_payload: Dict[str, Any],
        session_state: Optional[Any] = None,
    ) -> AdmissionResult:
        """
        Submits a new review mission from Antigravity.
        Validates against the MissionAdmissionGate and notifies listeners.
        """
        # Ensure orchestrator identity is set to antigravity if not specified
        if "orchestrator_identity" not in mission_payload:
            mission_payload["orchestrator_identity"] = "antigravity"

        mission = ReviewMission.from_dict(mission_payload)
        admission_result = self.orchestrator.admit(mission, session_state=session_state)

        self._notify("mission_admission", {
            "mission_id": mission.mission_id,
            "is_admitted": admission_result.is_admitted,
            "rejections": admission_result.rejections,
        })
        return admission_result

    async def execute_mission(
        self,
        mission_id: str,
        session_state: Optional[Any] = None,
    ) -> ReviewMissionResult:
        """
        Executes an admitted mission and streams progress events.
        """
        mission = self.orchestrator.get_mission(mission_id)
        if not mission:
            result = ReviewMissionResult(
                mission_id=mission_id,
                session_id="unknown",
                final_status=MissionLifecycleState.REJECTED,
                technical_verdict="UNVERIFIED",
                limitations=[f"Mission '{mission_id}' was not admitted or not found."],
            )
            return result

        self._notify("mission_started", {"mission_id": mission_id, "objective": mission.objective})

        result = await self.orchestrator.run_mission(mission, session_state=session_state)

        # Sanitize outbound observations for safety
        sanitized_observations = {}
        for k, v in result.observations.items():
            if isinstance(v, str):
                sanitized_observations[k] = sanitize_observed_text(v)
            else:
                sanitized_observations[k] = v

        outbound_payload = {
            "mission_id": result.mission_id,
            "final_status": result.final_status.value,
            "technical_verdict": result.technical_verdict,
            "completed_steps": len(result.completed_steps),
            "failed_steps": len(result.failed_steps),
            "unverified_steps": len(result.unverified_steps),
            "evidence_refs": result.evidence_refs,
            "duration_ms": result.duration_ms,
            "confidence": result.confidence,
        }
        self._notify("mission_completed", outbound_payload)
        return result

    def cancel_mission(self, mission_id: str, reason: str = "Cancelled by Antigravity controller") -> bool:
        """Cancels an in-flight review mission."""
        success = self.orchestrator.cancel_mission(mission_id, reason=reason)
        if success:
            self._notify("mission_cancelled", {"mission_id": mission_id, "reason": reason})
        return success

    def get_mission(self, mission_id: str) -> Optional[ReviewMission]:
        return self.orchestrator.get_mission(mission_id)

    def get_mission_status(self, mission_id: str) -> Optional[Dict[str, Any]]:
        m = self.orchestrator.get_mission(mission_id)
        if not m:
            return None
        res = self.orchestrator.get_mission_result(mission_id)
        return {
            "mission_id": m.mission_id,
            "session_id": m.session_id,
            "objective": m.objective,
            "lifecycle_status": m.lifecycle_status.value,
            "is_admitted": m.is_admitted,
            "has_result": res is not None,
            "technical_verdict": res.technical_verdict if res else None,
        }
