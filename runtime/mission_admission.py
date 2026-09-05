"""
Deterministic Mission Admission Gate (Architecture H / Phase 17).
Validates proposed ReviewMission authority envelopes against 13 strict constitutional criteria.
Enforces the sovereignty boundary: rejects malformed, ambiguous, or unconstrained missions.
Does NOT infer missing user intent or expand scope into unconstrained crawling.
"""

from __future__ import annotations
import logging
import time
from typing import Dict, List, Optional, Set, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.mission_models import (
    ReviewMission,
    AdmissionResult,
    MissionLifecycleState,
)
from runtime.errors import SessionNotFoundException

logger = logging.getLogger("desktop_webview.mission_admission")

# Recognized authoritative orchestrator identities
AUTHORIZED_ORCHESTRATORS: Set[str] = {
    "antigravity",
    "team_preview",
    "user",
    "developer",
    "test_harness",
    "adaptive_orchestrator",
}

# Maximum safety limits for autonomous mission execution
MAX_ACTION_BUDGET_CEILING = 100
MAX_DELEGATION_BUDGET_CEILING = 50
MAX_RECOVERY_BUDGET_CEILING = 10
MAX_DURATION_SEC_CEILING = 3600.0  # 1 hour absolute safety ceiling


class MissionAdmissionGate:
    """
    Deterministic gate validating mission authority prior to orchestrator admission.
    Enforces that the controlling layer has provided complete, unambiguous WHAT/WHY authority.
    """

    def __init__(self, session_manager: Optional[Any] = None):
        self.session_manager = session_manager

    def validate(
        self,
        mission: ReviewMission,
        session_state: Optional[Any] = None,
        current_epoch: Optional[int] = None,
        current_pid: Optional[int] = None,
    ) -> AdmissionResult:
        """
        Executes the 13-point deterministic validation protocol.
        Returns AdmissionResult with is_admitted=True if all points pass.
        """
        rejections: List[str] = []

        # 1. Session identity
        if not mission.session_id or not isinstance(mission.session_id, str):
            rejections.append("Point 1 (Session Identity): session_id must be a non-empty string.")
        else:
            resolved_session = session_state
            if resolved_session is None and self.session_manager is not None:
                try:
                    resolved_session = self.session_manager.get_session(mission.session_id)
                except Exception:
                    resolved_session = None

            if resolved_session is not None and getattr(resolved_session, "is_closed", False):
                rejections.append(f"Point 1 (Session Identity): Session '{mission.session_id}' is closed or terminated.")

        # 2. Application identity
        if not mission.app_identity and session_state is not None:
            # If not provided in mission, check if session has it
            pass
        elif mission.app_identity and session_state is not None:
            session_app = getattr(session_state, "app_id", None) or getattr(session_state, "application_name", None)
            mission_app = mission.app_identity.get("app_id") or mission.app_identity.get("name")
            if session_app and mission_app and str(session_app).lower() != str(mission_app).lower():
                rejections.append(
                    f"Point 2 (Application Identity): Mission app '{mission_app}' does not match session app '{session_app}'."
                )

        # 3. Objective
        if not mission.objective or not isinstance(mission.objective, str) or len(mission.objective.strip()) < 5:
            rejections.append("Point 3 (Objective): Objective must be a specific, non-empty description (min 5 characters).")
        elif mission.objective.strip().lower() in {"test", "review", "review app", "check", "run"}:
            rejections.append("Point 3 (Objective): Generic or ambiguous objective is rejected. Must describe specific business intent.")

        # 4. Scope (NO GENERAL CRAWLING)
        if not mission.declared_scope or not isinstance(mission.declared_scope, list) or len(mission.declared_scope) == 0:
            rejections.append("Point 4 (Declared Scope): declared_scope must be a non-empty list of specific surfaces or features.")
        else:
            ambiguous_tokens = {"*", "all", "entire app", "everything", "unspecified", "any"}
            for s in mission.declared_scope:
                if not s or not isinstance(s, str) or s.strip().lower() in ambiguous_tokens:
                    rejections.append(
                        f"Point 4 (Declared Scope): Ambiguous scope '{s}' is rejected. General application crawling is forbidden."
                    )
                    break

        # 5. Acceptance criteria
        if not mission.acceptance_criteria or not isinstance(mission.acceptance_criteria, list) or len(mission.acceptance_criteria) == 0:
            rejections.append("Point 5 (Acceptance Criteria): Mission must declare at least one explicit acceptance criterion.")
        else:
            for c in mission.acceptance_criteria:
                if not c or not isinstance(c, str) or len(c.strip()) < 3:
                    rejections.append(f"Point 5 (Acceptance Criteria): Criterion '{c}' is empty or insufficiently specific.")
                    break

        # 6. Authorization
        if not mission.orchestrator_identity or mission.orchestrator_identity.strip().lower() not in AUTHORIZED_ORCHESTRATORS:
            rejections.append(
                f"Point 6 (Authorization): Orchestrator '{mission.orchestrator_identity}' is not in authorized set {sorted(list(AUTHORIZED_ORCHESTRATORS))}."
            )

        # 7. Deadline
        if mission.max_duration_sec <= 0:
            rejections.append(f"Point 7 (Deadline): max_duration_sec must be positive (got {mission.max_duration_sec}).")
        elif mission.max_duration_sec > MAX_DURATION_SEC_CEILING:
            rejections.append(
                f"Point 7 (Deadline): max_duration_sec ({mission.max_duration_sec}) exceeds absolute ceiling of {MAX_DURATION_SEC_CEILING}s."
            )

        # 8. Action budget
        if mission.max_actions <= 0:
            rejections.append(f"Point 8 (Action Budget): max_actions must be > 0 (got {mission.max_actions}).")
        elif mission.max_actions > MAX_ACTION_BUDGET_CEILING:
            rejections.append(
                f"Point 8 (Action Budget): max_actions ({mission.max_actions}) exceeds maximum safety limit of {MAX_ACTION_BUDGET_CEILING}."
            )

        # 9. Delegation budget
        if mission.max_delegations <= 0:
            rejections.append(f"Point 9 (Delegation Budget): max_delegations must be > 0 (got {mission.max_delegations}).")
        elif mission.max_delegations > MAX_DELEGATION_BUDGET_CEILING:
            rejections.append(
                f"Point 9 (Delegation Budget): max_delegations ({mission.max_delegations}) exceeds maximum limit of {MAX_DELEGATION_BUDGET_CEILING}."
            )

        # 10. Recovery budget
        if mission.max_recoveries < 0:
            rejections.append(f"Point 10 (Recovery Budget): max_recoveries cannot be negative (got {mission.max_recoveries}).")
        elif mission.max_recoveries > MAX_RECOVERY_BUDGET_CEILING:
            rejections.append(
                f"Point 10 (Recovery Budget): max_recoveries ({mission.max_recoveries}) exceeds maximum limit of {MAX_RECOVERY_BUDGET_CEILING}."
            )

        # 11. Specialist roles
        if not mission.authorized_specialist_roles or len(mission.authorized_specialist_roles) == 0:
            rejections.append("Point 11 (Specialist Roles): authorized_specialist_roles must not be empty.")
        else:
            canonical_roles = set(SpecialistRole)
            for role in mission.authorized_specialist_roles:
                if role not in canonical_roles:
                    rejections.append(f"Point 11 (Specialist Roles): Role '{role}' is not a valid canonical SpecialistRole.")

        # 12. Prohibited-surface consistency
        allowed_set = {s.strip().lower() for s in mission.allowed_surfaces if isinstance(s, str)}
        prohibited_set = {s.strip().lower() for s in mission.prohibited_surfaces if isinstance(s, str)}
        intersection = allowed_set.intersection(prohibited_set)
        if intersection:
            rejections.append(
                f"Point 12 (Surface Consistency): Conflicting surfaces present in both allowed and prohibited sets: {sorted(list(intersection))}."
            )

        # 13. Stale session/target state
        if session_state is not None:
            sess_epoch = getattr(session_state, "current_epoch", None)
            if current_epoch is not None and sess_epoch is not None and current_epoch != sess_epoch:
                rejections.append(f"Point 13 (Stale State): Current epoch {sess_epoch} does not match expected {current_epoch}.")

            sess_pid = getattr(session_state, "target_pid", None)
            if current_pid is not None and sess_pid is not None and current_pid != sess_pid:
                rejections.append(f"Point 13 (Stale State): Process PID recycled: session PID={sess_pid} != expected {current_pid}.")

        if rejections:
            logger.warning(f"Mission {mission.mission_id} rejected at Admission Gate with {len(rejections)} violations: {rejections}")
            if mission.lifecycle_status == MissionLifecycleState.CREATED:
                mission.transition_to(MissionLifecycleState.VALIDATING, reason="Starting admission validation")
            mission.transition_to(MissionLifecycleState.REJECTED, reason="; ".join(rejections))
            return AdmissionResult(
                is_admitted=False,
                mission_id=mission.mission_id,
                rejections=rejections,
                admitted_mission=None,
            )

        # Validation passed: admit mission and seal authority
        if mission.lifecycle_status == MissionLifecycleState.CREATED:
            mission.transition_to(MissionLifecycleState.VALIDATING, reason="Starting admission validation")
        mission.transition_to(MissionLifecycleState.ADMITTED, reason="Admission gate criteria verified")
        mission.seal_authority()
        logger.info(f"Mission {mission.mission_id} admitted successfully by MissionAdmissionGate.")

        return AdmissionResult(
            is_admitted=True,
            mission_id=mission.mission_id,
            rejections=[],
            admitted_mission=mission,
        )
