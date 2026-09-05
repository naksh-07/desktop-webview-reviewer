"""
Review Mission Orchestrator (Architecture H / Phase 17).
Coordinates the end-to-end execution of admitted ReviewMissions.
Enforces:
- Sovereignty Boundary: Controlling agent decides WHAT/WHY; Reviewer decides HOW.
- Deterministic 9-state lifecycle & state transition matrix.
- Hard resource budgets: max duration, max actions, max delegations, max recoveries.
- Graceful cancellation preserving all evidence, trace, and diagnostics.
- Tripartite verdict discipline (PASS, FAIL, UNVERIFIED).
- Physical Reality Primacy: Physical Desktop Reality > Compositor Reality > DOM Reality.
- NO blind retries: recovery occurs only with verified diagnosis and circuit breaker approval.
"""

from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Dict, List, Optional, Set, Any

from runtime.specialist_contracts import SpecialistRole, SpecialistRegistry
from runtime.specialist_models import (
    SpecialistDelegation,
    DelegationScope,
    SpecialistResult,
    SpecialistResultStatus,
)
from runtime.specialist_dispatcher import SpecialistDispatcher
from runtime.diagnostics import DiagnosticAggregator, DiagnosticDiagnosis, FailureCategory
from runtime.recovery_engine import RecoveryEngine, RecoveryAction, RecoveryPolicy, CircuitBreaker
from runtime.trace_models import DesktopTraceEventType
from runtime.trace_engine import DesktopTraceEngine
from runtime.mission_models import (
    ReviewMission,
    DiscoveryCandidate,
    ReviewPlan,
    ReviewPlanStep,
    AdmissionResult,
    ReviewMissionResult,
    MissionLifecycleState,
    MissionAuthorityMutatedException,
)
from runtime.mission_admission import MissionAdmissionGate
from runtime.goal_discovery import GoalOrientedDiscoveryEngine
from runtime.review_plan import ReviewPlanBuilder
from runtime.observation_security import sanitize_observed_text

logger = logging.getLogger("desktop_webview.mission_orchestrator")


class ReviewMissionOrchestrator:
    """
    Primary mission orchestrator coordinating goal-oriented discovery, subordinate planning,
    specialist execution, diagnostic failure correlation, and bounded recovery.
    """

    def __init__(
        self,
        session_manager: Optional[Any] = None,
        dispatcher: Optional[SpecialistDispatcher] = None,
        recovery_engine: Optional[RecoveryEngine] = None,
        diagnostic_aggregator: Optional[DiagnosticAggregator] = None,
        admission_gate: Optional[MissionAdmissionGate] = None,
        discovery_engine: Optional[GoalOrientedDiscoveryEngine] = None,
    ):
        self.session_manager = session_manager
        self.dispatcher = dispatcher or SpecialistDispatcher(session_manager=session_manager)
        self.recovery_engine = recovery_engine or RecoveryEngine()
        self.diagnostic_aggregator = diagnostic_aggregator or DiagnosticAggregator()
        self.admission_gate = admission_gate or MissionAdmissionGate(session_manager=session_manager)
        self.discovery_engine = discovery_engine or GoalOrientedDiscoveryEngine(dispatcher=self.dispatcher)

        self._active_missions: Dict[str, ReviewMission] = {}
        self._cancellation_requests: Dict[str, str] = {}
        self._mission_results: Dict[str, ReviewMissionResult] = {}

    def admit(
        self,
        mission: ReviewMission,
        session_state: Optional[Any] = None,
    ) -> AdmissionResult:
        """Admits an incoming ReviewMission through the deterministic admission gate."""
        result = self.admission_gate.validate(mission, session_state=session_state)
        if result.is_admitted:
            self._active_missions[mission.mission_id] = mission
        return result

    def cancel_mission(self, mission_id: str, reason: str = "User requested cancellation") -> bool:
        """
        Requests cancellation of an in-flight mission.
        Halts further actions/delegations and preserves existing evidence and trace.
        """
        if mission_id not in self._active_missions:
            return False
        self._cancellation_requests[mission_id] = reason
        logger.info(f"Cancellation requested for mission {mission_id}: {reason}")
        return True

    def get_mission(self, mission_id: str) -> Optional[ReviewMission]:
        return self._active_missions.get(mission_id)

    def get_mission_result(self, mission_id: str) -> Optional[ReviewMissionResult]:
        return self._mission_results.get(mission_id)

    async def run_mission(
        self,
        mission: ReviewMission,
        session_state: Optional[Any] = None,
    ) -> ReviewMissionResult:
        """
        Executes an admitted ReviewMission through its bounded lifecycle:
        ADMITTED -> DISCOVERING -> PLANNING -> EXECUTING -> VERIFYING -> COLLECTING_EVIDENCE -> TERMINAL.
        """
        start_perf = time.perf_counter()
        start_time = time.time()
        deadline = start_time + mission.max_duration_sec

        # 1. Admission Check
        if not mission.is_admitted:
            admission_result = self.admit(mission, session_state=session_state)
            if not admission_result.is_admitted:
                result = ReviewMissionResult(
                    mission_id=mission.mission_id,
                    session_id=mission.session_id,
                    final_status=MissionLifecycleState.REJECTED,
                    technical_verdict="UNVERIFIED",
                    limitations=[f"Mission rejected at admission: {r}" for r in admission_result.rejections],
                    duration_ms=(time.perf_counter() - start_perf) * 1000,
                )
                self._mission_results[mission.mission_id] = result
                return result

        trace_eng: Optional[DesktopTraceEngine] = getattr(session_state, "trace_engine", None)
        self._emit_trace(trace_eng, DesktopTraceEventType.MISSION_LIFECYCLE, mission, details={"state": "ADMITTED"})

        # Budget tracking counters
        actions_taken = 0
        delegations_count = 0
        recoveries_count = 0
        completed_steps: List[Dict[str, Any]] = []
        failed_steps: List[Dict[str, Any]] = []
        unverified_steps: List[Dict[str, Any]] = []
        collected_diagnostics: List[Dict[str, Any]] = []
        recovery_history: List[Dict[str, Any]] = []
        evidence_references: List[str] = []
        trace_references: List[str] = []
        accumulated_observations: Dict[str, Any] = {}
        limitations: List[str] = []

        # 2. Check for early cancellation
        if mission.mission_id in self._cancellation_requests:
            return self._handle_cancellation(
                mission, start_perf, completed_steps, failed_steps, unverified_steps,
                accumulated_observations, collected_diagnostics, recovery_history,
                evidence_references, trace_references, limitations, actions_taken,
                delegations_count, recoveries_count
            )

        # 3. DISCOVERING Phase
        try:
            mission.transition_to(MissionLifecycleState.DISCOVERING, reason="Initiating bounded discovery")
            self._emit_trace(trace_eng, DesktopTraceEventType.MISSION_LIFECYCLE, mission, details={"state": "DISCOVERING"})

            candidates = await self.discovery_engine.discover_candidates(mission, session_state=session_state)
            self._emit_trace(
                trace_eng,
                DesktopTraceEventType.MISSION_DISCOVERY,
                mission,
                details={"discovered_candidates": len(candidates)},
            )

            if not candidates:
                logger.info(f"No review candidates discovered for mission {mission.mission_id} within declared scope.")
                mission.transition_to(MissionLifecycleState.COMPLETED, reason="Discovery found no relevant targets in authorized scope")
                result = ReviewMissionResult(
                    mission_id=mission.mission_id,
                    session_id=mission.session_id,
                    final_status=MissionLifecycleState.COMPLETED,
                    technical_verdict="UNVERIFIED",
                    limitations=["No review affordances found matching mission acceptance criteria inside declared scope."],
                    duration_ms=(time.perf_counter() - start_perf) * 1000,
                    budget_usage={
                        "actions": actions_taken,
                        "delegations": delegations_count,
                        "recoveries": recoveries_count,
                        "duration_sec": time.time() - start_time,
                    },
                )
                self._mission_results[mission.mission_id] = result
                return result

        except Exception as e:
            logger.exception(f"Discovery phase failed for mission {mission.mission_id}: {e}")
            mission.transition_to(MissionLifecycleState.FAILED, reason=f"Discovery exception: {e}")
            result = ReviewMissionResult(
                mission_id=mission.mission_id,
                session_id=mission.session_id,
                final_status=MissionLifecycleState.FAILED,
                technical_verdict="FAIL",
                limitations=[f"Discovery error: {e}"],
                duration_ms=(time.perf_counter() - start_perf) * 1000,
            )
            self._mission_results[mission.mission_id] = result
            return result

        # 4. PLANNING Phase
        if mission.mission_id in self._cancellation_requests:
            return self._handle_cancellation(
                mission, start_perf, completed_steps, failed_steps, unverified_steps,
                accumulated_observations, collected_diagnostics, recovery_history,
                evidence_references, trace_references, limitations, actions_taken,
                delegations_count, recoveries_count
            )

        mission.transition_to(MissionLifecycleState.PLANNING, reason="Synthesizing subordinate review plan")
        self._emit_trace(trace_eng, DesktopTraceEventType.MISSION_LIFECYCLE, mission, details={"state": "PLANNING"})

        review_plan = ReviewPlanBuilder.build_plan(mission, candidates)
        self._emit_trace(
            trace_eng,
            DesktopTraceEventType.MISSION_PLAN,
            mission,
            plan_id=review_plan.plan_id,
            details={"step_count": len(review_plan.steps), "est_actions": review_plan.total_estimated_actions},
        )

        # 5. EXECUTING Phase
        mission.transition_to(MissionLifecycleState.EXECUTING, reason="Executing subordinate review plan")
        self._emit_trace(trace_eng, DesktopTraceEventType.MISSION_LIFECYCLE, mission, plan_id=review_plan.plan_id, details={"state": "EXECUTING"})

        timed_out = False
        physical_reality_verified = False

        for step in review_plan.steps:
            # Check cancellation before each step
            if mission.mission_id in self._cancellation_requests:
                return self._handle_cancellation(
                    mission, start_perf, completed_steps, failed_steps, unverified_steps,
                    accumulated_observations, collected_diagnostics, recovery_history,
                    evidence_references, trace_references, limitations, actions_taken,
                    delegations_count, recoveries_count
                )

            # Check wall-clock deadline
            now = time.time()
            if now >= deadline:
                logger.warning(f"Mission {mission.mission_id} reached wall-clock deadline ({mission.max_duration_sec}s).")
                timed_out = True
                limitations.append(f"Mission halted: wall-clock deadline of {mission.max_duration_sec}s elapsed.")
                step.status = "SKIPPED"
                unverified_steps.append(step.to_dict())
                break

            # Check hard action budget
            if actions_taken >= mission.max_actions:
                logger.warning(f"Mission {mission.mission_id} reached hard action budget ({mission.max_actions}).")
                limitations.append(f"Mission halted: maximum action budget ({mission.max_actions}) reached.")
                step.status = "SKIPPED"
                unverified_steps.append(step.to_dict())
                break

            # Check hard delegation budget
            if delegations_count >= mission.max_delegations:
                logger.warning(f"Mission {mission.mission_id} reached hard delegation budget ({mission.max_delegations}).")
                limitations.append(f"Mission halted: maximum delegation budget ({mission.max_delegations}) reached.")
                step.status = "SKIPPED"
                unverified_steps.append(step.to_dict())
                break

            # Execute Step
            step.status = "RUNNING"
            step.started_at = time.time()

            delegation = SpecialistDelegation(
                role=step.specialist_role,
                task=step.expected_assertion,
                scope=DelegationScope(
                    session_id=mission.session_id,
                    allowed_screens=list(mission.allowed_surfaces),
                    max_actions=min(5, mission.max_actions - actions_taken),
                ),
                permitted_tools=SpecialistRegistry.get_contract(step.specialist_role).permitted_tools,
                timeout_sec=min(30.0, max(1.0, deadline - time.time())),
                allow_state_mutation=(step.specialist_role == SpecialistRole.TESTER),
                parameters=step.parameters,
            )
            step.delegation_id = delegation.delegation_id
            delegations_count += 1

            self._emit_trace(
                trace_eng,
                DesktopTraceEventType.SPECIALIST_LIFECYCLE,
                mission,
                plan_id=review_plan.plan_id,
                candidate_id=step.candidate_id,
                delegation_id=delegation.delegation_id,
                details={"role": step.specialist_role.value, "step_id": step.step_id, "status": "DISPATCHED"},
            )

            # Dispatch specialist
            spec_result: SpecialistResult = await self.dispatcher.dispatch(delegation, session_state=session_state)

            # Record metrics
            if step.specialist_role == SpecialistRole.TESTER:
                actions_taken += max(1, len(spec_result.tools_used))
            step.completed_at = time.time()
            accumulated_observations.update(spec_result.observations)
            evidence_references.extend(spec_result.evidence_refs)
            trace_references.extend(spec_result.trace_refs)

            if spec_result.status == SpecialistResultStatus.SUCCESS:
                step.status = "COMPLETED"
                step.result_summary = spec_result.answer
                completed_steps.append(step.to_dict())

                if step.specialist_role == SpecialistRole.REALITY_INSPECTOR:
                    # Check physical desktop observations
                    is_visible = spec_result.observations.get("is_visible", True)
                    is_cloaked = spec_result.observations.get("is_cloaked", False)
                    if is_visible and not is_cloaked:
                        physical_reality_verified = True
                    else:
                        limitations.append("Reality Inspector noted window is cloaked or occluded on desktop.")
            else:
                # Step failed!
                step.status = "FAILED"
                step.result_summary = f"{spec_result.status.value}: {spec_result.answer}"
                failed_steps.append(step.to_dict())

                # 6. Invoke Debugger / Diagnostic Aggregator
                diagnosis = self.diagnostic_aggregator.diagnose_failure(
                    session_state=session_state,
                    action_id=delegation.delegation_id,
                )
                collected_diagnostics.append(diagnosis.to_dict())
                logger.info(f"Step {step.step_id} failed. Diagnosis: {diagnosis.failure_category.value} - {diagnosis.root_cause_summary}")

                # 7. Evaluate Bounded Recovery (NO BLIND RETRIES)
                can_recover = (
                    diagnosis.is_recoverable
                    and recoveries_count < mission.max_recoveries
                    and not self.recovery_engine.circuit_breaker.is_blocked()
                    and bool(RecoveryPolicy.get_recovery_candidates(diagnosis.failure_category))
                )

                if can_recover:
                    logger.info(f"Attempting bounded recovery for category {diagnosis.failure_category.value} (attempt {recoveries_count + 1}/{mission.max_recoveries})...")
                    try:
                        rec_success, rec_record = await self.recovery_engine.attempt_recovery(
                            diagnosis=diagnosis,
                            session_state=session_state,
                            timeout_sec=min(15.0, max(1.0, deadline - time.time())),
                        )
                        recoveries_count += 1
                        recovery_history.append(rec_record.to_dict())

                        if rec_success:
                            logger.info(f"Recovery succeeded ({rec_record.action.value}). Retrying step {step.step_id}...")
                            # Retry step under bounded budget
                            if delegations_count < mission.max_delegations and (time.time() < deadline):
                                delegations_count += 1
                                retry_result = await self.dispatcher.dispatch(delegation, session_state=session_state)
                                if retry_result.status == SpecialistResultStatus.SUCCESS:
                                    step.status = "COMPLETED"
                                    step.result_summary = f"RECOVERED: {retry_result.answer}"
                                    failed_steps.pop()  # Remove from failed
                                    completed_steps.append(step.to_dict())
                                    logger.info(f"Retry of step {step.step_id} succeeded after recovery!")
                                    continue
                    except Exception as rec_err:
                        logger.warning(f"Recovery attempt failed: {rec_err}")

                # Non-recoverable or recovery failed -> stop further plan execution
                logger.warning(f"Execution halted following unrecoverable failure in step {step.step_id}.")
                break

        # 8. VERIFYING & Tripartite Verdict Resolution
        duration_ms = (time.perf_counter() - start_perf) * 1000

        # Physical reality primacy check: If reality inspection was not verified, we cannot grant PASS
        if timed_out:
            final_status = MissionLifecycleState.TIMED_OUT
            technical_verdict = "UNVERIFIED"
        elif mission.mission_id in self._cancellation_requests:
            final_status = MissionLifecycleState.CANCELLED
            technical_verdict = "UNVERIFIED"
        elif len(failed_steps) > 0:
            final_status = MissionLifecycleState.FAILED
            technical_verdict = "FAIL"
        elif len(completed_steps) == 0:
            final_status = MissionLifecycleState.UNVERIFIED
            technical_verdict = "UNVERIFIED"
        elif SpecialistRole.REALITY_INSPECTOR in mission.authorized_specialist_roles and not physical_reality_verified:
            final_status = MissionLifecycleState.UNVERIFIED
            technical_verdict = "UNVERIFIED"
            limitations.append("Truth Hierarchy: Physical desktop reality was not verified (window occluded or inspection missing).")
        else:
            final_status = MissionLifecycleState.COMPLETED
            technical_verdict = "PASS"

        try:
            mission.transition_to(final_status, reason=f"Mission concluded with verdict {technical_verdict}")
        except Exception:
            pass

        self._emit_trace(
            trace_eng,
            DesktopTraceEventType.MISSION_LIFECYCLE,
            mission,
            details={"state": final_status.value, "verdict": technical_verdict},
        )

        result = ReviewMissionResult(
            mission_id=mission.mission_id,
            session_id=mission.session_id,
            final_status=final_status,
            technical_verdict=technical_verdict,
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            unverified_steps=unverified_steps,
            observations=accumulated_observations,
            diagnostics=collected_diagnostics,
            recovery_attempts=recovery_history,
            evidence_refs=list(set(evidence_references)),
            trace_refs=list(set(trace_references)),
            limitations=limitations,
            confidence=1.0 if technical_verdict == "PASS" else 0.8,
            duration_ms=duration_ms,
            budget_usage={
                "actions": actions_taken,
                "max_actions": mission.max_actions,
                "delegations": delegations_count,
                "max_delegations": mission.max_delegations,
                "recoveries": recoveries_count,
                "max_recoveries": mission.max_recoveries,
                "duration_sec": time.time() - start_time,
                "max_duration_sec": mission.max_duration_sec,
            },
        )
        self._mission_results[mission.mission_id] = result
        logger.info(f"Mission {mission.mission_id} finished in {duration_ms:.1f}ms. Status: {final_status.value}, Verdict: {technical_verdict}")
        return result

    def _handle_cancellation(
        self,
        mission: ReviewMission,
        start_perf: float,
        completed_steps: List[Dict[str, Any]],
        failed_steps: List[Dict[str, Any]],
        unverified_steps: List[Dict[str, Any]],
        observations: Dict[str, Any],
        diagnostics: List[Dict[str, Any]],
        recoveries: List[Dict[str, Any]],
        evidence_refs: List[str],
        trace_refs: List[str],
        limitations: List[str],
        actions: int,
        delegations: int,
        recoveries_count: int,
    ) -> ReviewMissionResult:
        reason = self._cancellation_requests.get(mission.mission_id, "User requested cancellation")
        try:
            mission.transition_to(MissionLifecycleState.CANCELLED, reason=reason)
        except Exception:
            pass

        result = ReviewMissionResult(
            mission_id=mission.mission_id,
            session_id=mission.session_id,
            final_status=MissionLifecycleState.CANCELLED,
            technical_verdict="UNVERIFIED",
            completed_steps=completed_steps,
            failed_steps=failed_steps,
            unverified_steps=unverified_steps,
            observations=observations,
            diagnostics=diagnostics,
            recovery_attempts=recoveries,
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            limitations=limitations + [f"Mission cancelled: {reason}"],
            duration_ms=(time.perf_counter() - start_perf) * 1000,
            budget_usage={
                "actions": actions,
                "delegations": delegations,
                "recoveries": recoveries_count,
            },
            cancellation_reason=reason,
        )
        self._mission_results[mission.mission_id] = result
        return result

    def _emit_trace(
        self,
        trace_eng: Optional[DesktopTraceEngine],
        event_type: DesktopTraceEventType,
        mission: ReviewMission,
        plan_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        delegation_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        if not trace_eng:
            return
        try:
            trace_eng.emit(
                event_type=event_type,
                session_id=mission.session_id,
                mission_id=mission.mission_id,
                plan_id=plan_id,
                candidate_id=candidate_id,
                delegation_id=delegation_id,
                details=details,
            )
        except Exception as e:
            logger.debug(f"Trace emission failed: {e}")
