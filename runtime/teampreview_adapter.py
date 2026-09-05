"""
TeamPreview Presentation Adapter (Architecture H / Phase 18).
Treats TeamPreview strictly as a passive, non-authoritative presentation/preview consumer.
Provides read-only queries for mission progression, physical desktop snapshots,
specialist activity, diagnostics, and cryptographic evidence catalogs.
ENFORCES THE ZERO-MUTATION LAW: TeamPreview possesses ZERO authority to execute actions,
invoke specialists, alter mission scope, or bypass admission gates.
"""

from __future__ import annotations
import logging
from typing import Dict, List, Optional, Any

from runtime.mission_models import ReviewMission, ReviewMissionResult
from runtime.mission_orchestrator import ReviewMissionOrchestrator
from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.teampreview_adapter")


class TeamPreviewMutationForbiddenException(DesktopAutomationException):
    """Raised when an illegal attempt is made to execute actions or alter missions via TeamPreview."""
    pass


class TeamPreviewConsumer:
    """
    Strictly read-only presentation consumer for TeamPreview.
    Aggregates passive UI state, visual reality frames, specialist feeds, and evidence for display.
    """

    def __init__(self, orchestrator: ReviewMissionOrchestrator):
        self.orchestrator = orchestrator

    def get_mission_overview(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Returns read-only summary of the mission status, progress, and budgets."""
        mission = self.orchestrator.get_mission(mission_id)
        if not mission:
            return None

        result = self.orchestrator.get_mission_result(mission_id)
        return {
            "mission_id": mission.mission_id,
            "session_id": mission.session_id,
            "objective": mission.objective,
            "lifecycle_status": mission.lifecycle_status.value,
            "declared_scope": list(mission.declared_scope),
            "allowed_surfaces": list(mission.allowed_surfaces),
            "acceptance_criteria": list(mission.acceptance_criteria),
            "max_duration_sec": mission.max_duration_sec,
            "max_actions": mission.max_actions,
            "max_delegations": mission.max_delegations,
            "max_recoveries": mission.max_recoveries,
            "is_admitted": mission.is_admitted,
            "created_at": mission.created_at,
            "completed_at": mission.completed_at,
            "final_verdict": result.technical_verdict if result else None,
            "budget_usage": result.budget_usage if result else {},
        }

    def get_reality_snapshot(self, session_id: str, session_state: Optional[Any] = None) -> Dict[str, Any]:
        """
        Returns passive desktop reality state: DWM inspection, window bounds, and occlusion metrics.
        """
        supervisor = getattr(session_state, "native_supervisor", None)
        target_win = getattr(session_state, "target_window", None)
        target_hwnd = target_win.hwnd if target_win else getattr(session_state, "target_hwnd", None)

        reality_view: Dict[str, Any] = {
            "session_id": session_id,
            "target_hwnd": hex(target_hwnd) if target_hwnd else None,
            "is_visible": True,
            "is_cloaked": False,
            "is_iconic": False,
            "bounds": None,
            "window_title": None,
        }

        if supervisor and target_hwnd:
            try:
                insp = supervisor.inspect_window(target_hwnd)
                reality_view.update({
                    "is_visible": insp.is_visible,
                    "is_cloaked": insp.is_cloaked,
                    "is_iconic": insp.is_iconic,
                    "bounds": [insp.bounds.x, insp.bounds.y, insp.bounds.width, insp.bounds.height],
                    "window_title": insp.title,
                })
            except Exception as e:
                reality_view["error"] = str(e)

        return reality_view

    def get_specialist_feed(self, mission_id: str) -> List[Dict[str, Any]]:
        """Returns read-only history of specialist assignments and audits for display."""
        mission = self.orchestrator.get_mission(mission_id)
        if not mission:
            return []
        return [
            {
                "from_state": entry.get("from_state"),
                "to_state": entry.get("to_state"),
                "timestamp": entry.get("timestamp"),
                "reason": entry.get("reason"),
            }
            for entry in mission.lifecycle_history
        ]

    def get_diagnostics_feed(self, mission_id: str) -> List[Dict[str, Any]]:
        """Returns read-only list of diagnostic classifications and failure analyses."""
        result = self.orchestrator.get_mission_result(mission_id)
        if not result:
            return []
        return result.diagnostics

    def get_evidence_catalog(self, mission_id: str) -> List[Dict[str, Any]]:
        """Returns read-only evidence artifact references and manifest digests."""
        result = self.orchestrator.get_mission_result(mission_id)
        if not result:
            return []
        return [
            {"evidence_ref": ref, "type": "artifact"}
            for ref in result.evidence_refs
        ]

    def get_final_result(self, mission_id: str) -> Optional[Dict[str, Any]]:
        """Returns the completed structured result envelope."""
        result = self.orchestrator.get_mission_result(mission_id)
        if not result:
            return None
        return result.to_dict()

    # -------------------------------------------------------------------------
    # ZERO MUTATION LAW: Defend against UI Backdoors and Direct Execution Attempts
    # -------------------------------------------------------------------------
    def execute_action(self, *args: Any, **kwargs: Any) -> None:
        raise TeamPreviewMutationForbiddenException(
            "Constitutional violation: TeamPreview is a strictly read-only presentation consumer. "
            "Direct action execution is strictly forbidden. Commands must travel through controlling agent."
        )

    def invoke_specialist(self, *args: Any, **kwargs: Any) -> None:
        raise TeamPreviewMutationForbiddenException(
            "Constitutional violation: TeamPreview cannot invoke specialist subagents directly."
        )

    def alter_mission_scope(self, *args: Any, **kwargs: Any) -> None:
        raise TeamPreviewMutationForbiddenException(
            "Constitutional violation: TeamPreview cannot alter mission scope or acceptance criteria."
        )

    def bypass_admission(self, *args: Any, **kwargs: Any) -> None:
        raise TeamPreviewMutationForbiddenException(
            "Constitutional violation: TeamPreview cannot bypass mission admission gates."
        )
