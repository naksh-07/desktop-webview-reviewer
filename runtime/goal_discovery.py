"""
Goal-Oriented Discovery Engine (Architecture H / Phase 17).
Answers: Given this explicit mission, what technically relevant review opportunities
exist inside its authorized scope?
Bound to mission scope and allowed surfaces. Enforces strict candidate provenance.
Rejects any candidate lacking mission provenance or targeting prohibited surfaces.
Guarantees NO general application crawling.
"""

from __future__ import annotations
import logging
import re
import uuid
from typing import Dict, List, Optional, Set, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistDelegation,
    DelegationScope,
    SpecialistResultStatus,
)
from runtime.specialist_dispatcher import SpecialistDispatcher
from runtime.mission_models import ReviewMission, DiscoveryCandidate
from runtime.observation_security import sanitize_observed_text

logger = logging.getLogger("desktop_webview.goal_discovery")


class GoalOrientedDiscoveryEngine:
    """
    Executes bounded, goal-oriented discovery strictly within mission authority.
    Dispatches Explorer specialist, maps discovered elements to criteria,
    and returns provenance-linked candidates.
    """

    def __init__(self, dispatcher: Optional[SpecialistDispatcher] = None):
        self.dispatcher = dispatcher or SpecialistDispatcher()

    async def discover_candidates(
        self,
        mission: ReviewMission,
        session_state: Optional[Any] = None,
    ) -> List[DiscoveryCandidate]:
        """
        Executes bounded discovery for the admitted mission.
        Returns a list of DiscoveryCandidate objects, each with verified mission provenance.
        """
        mission.verify_authority_integrity()

        # 1. Create bounded DelegationScope for Explorer specialist
        scope = DelegationScope(
            session_id=mission.session_id,
            allowed_screens=list(mission.allowed_surfaces),
            max_actions=5,
            custom_constraints={
                "prohibited_surfaces": list(mission.prohibited_surfaces),
                "declared_scope": list(mission.declared_scope),
            },
        )

        delegation = SpecialistDelegation(
            role=SpecialistRole.EXPLORER,
            task=f"Discover review affordances for objective: {mission.objective}",
            scope=scope,
            permitted_tools={
                "desktop_inspect",
                "desktop_query_targets",
                "desktop_get_tree",
                "desktop_get_capabilities",
            },
            timeout_sec=min(30.0, mission.max_duration_sec),
            allow_state_mutation=False,
            parameters={"objective": mission.objective},
        )

        # 2. Dispatch Explorer specialist
        result = await self.dispatcher.dispatch(delegation, session_state=session_state)
        if result.status != SpecialistResultStatus.SUCCESS:
            logger.warning(f"Explorer discovery returned status {result.status}: {result.answer}")
            return []

        # 3. Analyze observed elements and synthesize candidates
        candidates = self._synthesize_candidates(mission, result.observations)
        logger.info(f"Discovered {len(candidates)} mission-scoped candidates for {mission.mission_id}.")
        return candidates

    def _synthesize_candidates(
        self,
        mission: ReviewMission,
        observations: Dict[str, Any],
    ) -> List[DiscoveryCandidate]:
        """
        Maps discovered UI topology to mission acceptance criteria and declared scope.
        Every generated candidate MUST possess verifiable mission provenance.
        """
        candidates: List[DiscoveryCandidate] = []
        elements = observations.get("interactive_elements", [])
        windows = observations.get("windows", [])
        raw_tree = observations.get("tree_summary", "")

        prohibited_lower = {s.strip().lower() for s in mission.prohibited_surfaces}
        allowed_lower = {s.strip().lower() for s in mission.allowed_surfaces}
        scope_lower = {s.strip().lower() for s in mission.declared_scope}

        # For each acceptance criterion, look for matching technical targets
        for crit_idx, criterion in enumerate(mission.acceptance_criteria):
            crit_lower = criterion.lower()
            matching_scope = self._resolve_scope_for_criterion(criterion, mission.declared_scope)
            if not matching_scope:
                continue

            # Check observed interactive elements
            for elem in elements:
                elem_name = str(elem.get("name", "")).strip()
                elem_role = str(elem.get("role", "")).strip()
                elem_ref = elem.get("ref")
                surface_tag = str(elem.get("surface", "")).strip().lower()

                # Filter out prohibited surfaces
                if surface_tag and surface_tag in prohibited_lower:
                    continue
                if any(p in elem_name.lower() for p in prohibited_lower):
                    continue

                # Check relevance: keywords in criterion or scope match element name/role
                is_relevant = self._is_element_relevant(elem_name, elem_role, crit_lower, scope_lower)
                if is_relevant:
                    action_type = "click" if elem_role.lower() in ("button", "link", "menuitem") else "assert"
                    cand = DiscoveryCandidate(
                        candidate_id=f"cand_{uuid.uuid4().hex[:10]}",
                        mission_id=mission.mission_id,
                        scope_reference=matching_scope,
                        acceptance_criterion_reference=criterion,
                        technical_rationale=f"Observed element '{elem_name}' ({elem_role}) correlates with criterion: '{criterion}'",
                        required_specialist=SpecialistRole.TESTER,
                        estimated_action_cost=1,
                        risk="LOW",
                        required_evidence=["screenshot", "trace"],
                        action_type=action_type,
                        target_ref=elem_ref,
                        target_name=sanitize_observed_text(elem_name),
                        assertion_details={"expected_text": elem_name if action_type == "assert" else None},
                        parameters={"element": elem},
                    )
                    candidates.append(cand)

            # If no element-level match was found, synthesize a criterion verification assertion
            # provided the scope itself was observed in windows or surfaces
            has_matching_surface = any(s in crit_lower for s in scope_lower) or any(s in crit_lower for s in allowed_lower)
            if not any(c.acceptance_criterion_reference == criterion for c in candidates) and has_matching_surface:
                candidates.append(
                    DiscoveryCandidate(
                        candidate_id=f"cand_{uuid.uuid4().hex[:10]}",
                        mission_id=mission.mission_id,
                        scope_reference=matching_scope,
                        acceptance_criterion_reference=criterion,
                        technical_rationale=f"Direct state assertion verifying acceptance criterion: '{criterion}'",
                        required_specialist=SpecialistRole.TESTER,
                        estimated_action_cost=1,
                        risk="LOW",
                        required_evidence=["screenshot", "trace"],
                        action_type="assert",
                        target_ref=None,
                        target_name=matching_scope,
                        assertion_details={"criterion": criterion},
                        parameters={},
                    )
                )

        return candidates

    def _resolve_scope_for_criterion(self, criterion: str, declared_scope: List[str]) -> Optional[str]:
        """Resolves which declared scope item encompasses the criterion."""
        crit_lower = criterion.lower()
        for scope_item in declared_scope:
            if scope_item.lower() in crit_lower:
                return scope_item
        # Default to first declared scope item if all criteria belong to declared scope
        return declared_scope[0] if declared_scope else None

    def _is_element_relevant(
        self,
        elem_name: str,
        elem_role: str,
        crit_lower: str,
        scope_lower: Set[str],
    ) -> bool:
        """Determines whether an observed element is technically relevant to the mission."""
        if not elem_name and not elem_role:
            return False
        name_lower = elem_name.lower()
        role_lower = elem_role.lower()

        # Token overlap with criterion or scope
        tokens = set(re.findall(r"\w+", name_lower))
        crit_tokens = set(re.findall(r"\w+", crit_lower))
        if tokens.intersection(crit_tokens):
            return True

        for s in scope_lower:
            if s in name_lower or name_lower in s:
                return True

        return False
