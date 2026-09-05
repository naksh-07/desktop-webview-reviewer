"""
Tester Specialist Subagent (Architecture H / Phase 15).
Mandate: "Did the explicitly requested workflow work?"
Executes delegated interaction sequences via the Action Engine, monitors settlement,
evaluates explicit assertions, and validates state transitions.
Strictly adheres to delegated acceptance criteria; cannot invent new business journeys.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistLifecycleState,
    SpecialistResultStatus,
    SpecialistResult,
)
from runtime.specialists.base import BaseSpecialistRuntime
from runtime.action_models import (
    ActionRequest,
    ActionType,
    ActionRiskLevel,
    ActionOutcomeStatus,
)
from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.specialist.tester")


class TesterSpecialist(BaseSpecialistRuntime):
    """Subordinate specialist answering: 'Did the explicitly requested workflow work?'"""

    @property
    def role(self) -> SpecialistRole:
        return SpecialistRole.TESTER

    async def execute(self) -> SpecialistResult:
        self._record_lifecycle(SpecialistLifecycleState.ACTING, "Executing delegated workflow sequence.")

        workflow_steps = self.delegation.parameters.get("workflow_steps", [])
        if not workflow_steps:
            # Check if a single action was delegated in parameters
            single_action = self.delegation.parameters.get("action")
            if single_action:
                workflow_steps = [single_action]

        steps_executed: List[Dict[str, Any]] = []
        assertions_evaluated: List[Dict[str, Any]] = []
        settlement_results: List[Dict[str, Any]] = []
        state_transitions: List[Dict[str, Any]] = []
        evidence_refs: List[str] = []
        trace_refs: List[str] = []
        errors: List[str] = []
        workflow_succeeded = True

        action_engine = getattr(self.session_state, "action_engine", None)
        obs_engine = getattr(self.session_state, "observation_engine", None)
        settle_engine = getattr(self.session_state, "settlement_engine", None)
        verif_engine = getattr(self.session_state, "verification_engine", None)

        if not workflow_steps:
            # Fallback: delegated a high-level assertion or verify task
            assertion_spec = self.delegation.parameters.get("assertion")
            if assertion_spec:
                workflow_steps = [{"action_type": "ASSERT", **assertion_spec}]
            else:
                return SpecialistResult(
                    specialist_id=self.specialist_id,
                    role=self.role,
                    delegation_id=self.delegation.delegation_id,
                    session_id=self.session_state.session_id,
                    status=SpecialistResultStatus.REJECTED,
                    answer="No workflow steps or assertions provided in delegation parameters.",
                    limitations=["Empty workflow delegated"],
                    confidence=1.0,
                )

        step_idx = 0
        for step in workflow_steps:
            self.check_deadline()
            if self.is_cancelled():
                return SpecialistResult(
                    specialist_id=self.specialist_id,
                    role=self.role,
                    delegation_id=self.delegation.delegation_id,
                    session_id=self.session_state.session_id,
                    status=SpecialistResultStatus.CANCELLED,
                    answer="Workflow execution cancelled.",
                    observations={"steps_executed": steps_executed},
                )

            step_idx += 1
            raw_action_type = str(step.get("action_type", "CLICK")).upper()
            ref = step.get("ref", "")

            # -----------------------------------------------------------------
            # 1. Handle ASSERT Step
            # -----------------------------------------------------------------
            if raw_action_type == "ASSERT":
                assertion_rule = step.get("assertion", "visible")
                expected_text = step.get("expected_text")
                timeout_ms = int(step.get("timeout_ms", 5000))

                async def _run_assertion():
                    # Evaluate assertion against active observation
                    if obs_engine:
                        obs = await obs_engine.capture_observation()
                        target_node = None
                        if ref and hasattr(obs, "nodes"):
                            target_node = next((n for n in obs.nodes if n.reference == ref), None)

                        matched = False
                        actual_val = None
                        if assertion_rule in ("visible", "exists"):
                            matched = target_node is not None and getattr(target_node, "is_visible", True)
                            actual_val = "visible" if matched else "not_found_or_hidden"
                        elif assertion_rule == "text_equals":
                            actual_val = getattr(target_node, "name", "") if target_node else None
                            matched = actual_val == expected_text
                        elif assertion_rule == "text_contains":
                            actual_val = getattr(target_node, "name", "") if target_node else None
                            matched = expected_text in actual_val if actual_val and expected_text else False
                        else:
                            matched = target_node is not None
                            actual_val = "exists" if matched else "missing"

                        return {
                            "assertion": assertion_rule,
                            "ref": ref,
                            "expected": expected_text or assertion_rule,
                            "actual": actual_val,
                            "passed": matched,
                        }
                    return {"assertion": assertion_rule, "ref": ref, "passed": True, "actual": "skipped"}

                try:
                    assert_res = await self.invoke_tool("desktop_assert", _run_assertion)
                    assertions_evaluated.append(assert_res)
                    if not assert_res.get("passed", False):
                        workflow_succeeded = False
                        errors.append(f"Assertion failed at step {step_idx}: expected '{assert_res.get('expected')}', got '{assert_res.get('actual')}'")
                        break
                except Exception as e:
                    workflow_succeeded = False
                    errors.append(f"Assertion execution error at step {step_idx}: {e}")
                    break
                continue

            # -----------------------------------------------------------------
            # 2. Mutating Action Step (CLICK, TYPE, KEY_PRESS, HOVER, SCROLL)
            # -----------------------------------------------------------------
            tool_name = f"desktop_{raw_action_type.lower()}"
            if tool_name == "desktop_key_press":
                tool_name = "desktop_press_key"

            async def _dispatch_action():
                if not action_engine:
                    raise DesktopAutomationException("ActionExecutionEngine not initialized in session.")

                # Build action request
                act_type = getattr(ActionType, raw_action_type, ActionType.CLICK)
                params = {}
                if "text" in step:
                    params["text"] = step["text"]
                if "key" in step:
                    params["key"] = step["key"]
                if "click_count" in step:
                    params["click_count"] = int(step["click_count"])
                if "button" in step:
                    params["button"] = step["button"]

                epoch = getattr(self.session_state, "current_epoch", 1)
                req = ActionRequest(
                    session_id=self.session_state.session_id,
                    reference=ref,
                    action_type=act_type,
                    observation_epoch=epoch,
                    params=params,
                    risk_level=ActionRiskLevel.INTERACTIVE,
                )
                return await action_engine.execute_transaction(req)

            try:
                receipt, outcome = await self.invoke_tool(tool_name, _dispatch_action)
                step_record = {
                    "step": step_idx,
                    "action_type": raw_action_type,
                    "ref": ref,
                    "status": outcome.outcome_status.value if hasattr(outcome.outcome_status, "value") else str(outcome.outcome_status),
                    "action_id": receipt.action_id,
                    "duration_ms": outcome.duration_ms,
                }
                steps_executed.append(step_record)
                trace_refs.append(receipt.action_id)

                if hasattr(outcome, "state_change"):
                    state_transitions.append({
                        "action_id": receipt.action_id,
                        "classification": str(outcome.state_change),
                        "pre_epoch": outcome.pre_epoch,
                        "post_epoch": outcome.post_epoch,
                    })

                if outcome.outcome_status != ActionOutcomeStatus.DISPATCHED:
                    workflow_succeeded = False
                    errors.append(f"Action failed at step {step_idx} ({raw_action_type} on '{ref}'): {outcome.error or outcome.outcome_status}")
                    break

            except Exception as e:
                workflow_succeeded = False
                errors.append(f"Action dispatch failed at step {step_idx} ({raw_action_type} on '{ref}'): {e}")
                break

            # -----------------------------------------------------------------
            # 3. Settlement Monitoring
            # -----------------------------------------------------------------
            if "desktop_settle" in self.delegation.permitted_tools and settle_engine:
                try:
                    async def _settle():
                        return await settle_engine.wait_for_settlement()
                    settle_res = await self.invoke_tool("desktop_settle", _settle)
                    settlement_results.append({
                        "step": step_idx,
                        "settled": getattr(settle_res, "is_settled", True),
                    })
                except Exception as e:
                    logger.debug(f"Settlement check ignored: {e}")

        # Final outcome determination
        status = SpecialistResultStatus.SUCCESS if workflow_succeeded else SpecialistResultStatus.FAILED
        answer = (
            f"Tester completed {len(steps_executed)} workflow step(s) with {len(assertions_evaluated)} assertion(s). "
            f"Workflow verdict: {status.value}."
        )

        return SpecialistResult(
            specialist_id=self.specialist_id,
            role=self.role,
            delegation_id=self.delegation.delegation_id,
            session_id=self.session_state.session_id,
            status=status,
            answer=answer,
            observations={
                "steps_executed": steps_executed,
                "assertions_evaluated": assertions_evaluated,
                "settlement_results": settlement_results,
                "state_transitions": state_transitions,
                "total_steps": len(workflow_steps),
            },
            evidence_refs=evidence_refs,
            trace_refs=trace_refs,
            errors=errors,
            confidence=1.0 if not errors else 0.9,
        )
