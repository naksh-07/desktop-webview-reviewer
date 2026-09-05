"""
Review Plan Builder (Architecture H / Phase 17).
Generates a subordinate ReviewPlan from mission-authorized DiscoveryCandidates.
The plan stages interaction testing, physical reality inspection, and evidence sealing.
The plan is strictly subordinate to the mission: it can order authorized work,
but CANNOT expand scope, exceed budgets, or authorize new specialist roles.
"""

from __future__ import annotations
import logging
import uuid
from typing import Dict, List, Optional, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.mission_models import (
    ReviewMission,
    DiscoveryCandidate,
    ReviewPlan,
    ReviewPlanStep,
)
from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.review_plan")


class PlanBudgetExceededException(DesktopAutomationException):
    """Raised when a plan cannot be constructed within mission hard budgets."""
    pass


class ReviewPlanBuilder:
    """
    Constructs an executable, budget-capped ReviewPlan subordinate to the ReviewMission.
    """

    @classmethod
    def build_plan(
        cls,
        mission: ReviewMission,
        candidates: List[DiscoveryCandidate],
    ) -> ReviewPlan:
        """
        Builds and orders the ReviewPlan steps.
        Enforces mission provenance, specialist authorization, and hard budget bounds.
        """
        mission.verify_authority_integrity()
        plan_id = f"plan_{uuid.uuid4().hex[:10]}"
        steps: List[ReviewPlanStep] = []
        total_actions = 0

        authorized_roles = set(mission.authorized_specialist_roles)
        prohibited_lower = {s.strip().lower() for s in mission.prohibited_surfaces}

        # 1. Stage interaction & assertion steps from discovery candidates
        for cand in candidates:
            # Provenance verification
            if cand.mission_id != mission.mission_id:
                logger.warning(f"Rejecting candidate {cand.candidate_id}: mission_id mismatch ({cand.mission_id} != {mission.mission_id})")
                continue

            if cand.target_name and cand.target_name.lower() in prohibited_lower:
                logger.warning(f"Rejecting candidate {cand.candidate_id}: targets prohibited surface '{cand.target_name}'")
                continue

            if cand.required_specialist not in authorized_roles:
                logger.warning(f"Rejecting candidate {cand.candidate_id}: required role {cand.required_specialist} not authorized in mission.")
                continue

            # Budget check
            if total_actions + cand.estimated_action_cost > mission.max_actions:
                logger.warning(f"Action budget ({mission.max_actions}) reached; stopping candidate inclusion.")
                break
            if len(steps) >= mission.max_delegations - 2:  # Reserve 2 slots for Reality Inspector & Evidence Specialist
                logger.warning(f"Delegation budget limit approached; stopping candidate inclusion.")
                break

            step = ReviewPlanStep(
                step_id=f"step_{uuid.uuid4().hex[:8]}",
                mission_id=mission.mission_id,
                candidate_id=cand.candidate_id,
                acceptance_criterion=cand.acceptance_criterion_reference,
                specialist_role=cand.required_specialist,
                expected_observation=f"Observe target element '{cand.target_name or cand.target_ref}'",
                expected_assertion=f"Satisfy criterion: {cand.acceptance_criterion_reference}",
                evidence_requirement=list(cand.required_evidence),
                parameters={
                    "action_type": cand.action_type,
                    "target_ref": cand.target_ref,
                    "target_name": cand.target_name,
                    "assertion_details": cand.assertion_details,
                    "parameters": cand.parameters,
                },
            )
            steps.append(step)
            total_actions += cand.estimated_action_cost

        # 2. Stage Physical Reality Inspection step
        if SpecialistRole.REALITY_INSPECTOR in authorized_roles and len(steps) < mission.max_delegations:
            reality_step = ReviewPlanStep(
                step_id=f"step_{uuid.uuid4().hex[:8]}",
                mission_id=mission.mission_id,
                candidate_id="cand_reality_verification",
                acceptance_criterion="Authoritative Physical Desktop Reality Verification",
                specialist_role=SpecialistRole.REALITY_INSPECTOR,
                expected_observation="Inspect native DWM window occlusion, visibility, and desktop rendering.",
                expected_assertion="Window is physically visible, uncloaked, non-iconic, and rendering on active desktop.",
                evidence_requirement=["native_desktop_screenshot", "dwm_window_forensics"],
                parameters={"enforce_physical_primacy": True},
            )
            steps.append(reality_step)

        # 3. Stage Cryptographic Evidence Packaging step
        if SpecialistRole.EVIDENCE_SPECIALIST in authorized_roles and len(steps) < mission.max_delegations:
            evidence_step = ReviewPlanStep(
                step_id=f"step_{uuid.uuid4().hex[:8]}",
                mission_id=mission.mission_id,
                candidate_id="cand_evidence_sealing",
                acceptance_criterion="Cryptographic Evidence Manifest & SHA-256 Chain of Custody",
                specialist_role=SpecialistRole.EVIDENCE_SPECIALIST,
                expected_observation="Collect, hash, and seal all generated screenshots, logs, and trace events.",
                expected_assertion="Evidence package sealed with valid SHA-256 hashes and tripartite verdict.",
                evidence_requirement=["evidence_manifest_json", "sha256_hash_verification"],
                parameters={"test_name": mission.objective[:60]},
            )
            steps.append(evidence_step)

        plan = ReviewPlan(
            plan_id=plan_id,
            mission_id=mission.mission_id,
            steps=steps,
            total_estimated_actions=total_actions,
            total_estimated_delegations=len(steps),
        )
        logger.info(f"Generated ReviewPlan {plan.plan_id} with {len(steps)} steps (est actions={total_actions}).")
        return plan
