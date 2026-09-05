"""
Bounded Recovery Engine, Reliability Policy & Circuit Breaker (Architecture H / Phase 16).
Restores runtime and testability after known transient failures while preserving
the original mission, acceptance criteria, and failure evidence.
Enforces NO BLIND RETRIES and Anti-Retry-Storm Circuit Breaking.
"""

from __future__ import annotations
import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any, Tuple

from runtime.diagnostics import FailureCategory, DiagnosticDiagnosis
from runtime.trace_models import DesktopTraceEventType
from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.recovery")


class RecoveryAction(str, Enum):
    """The canonical bounded recovery actions."""
    RECONNECT = "RECONNECT"
    REATTACH = "REATTACH"
    WAIT_FOR_PROCESS = "WAIT_FOR_PROCESS"
    WAIT_FOR_WEBVIEW = "WAIT_FOR_WEBVIEW"
    REFRESH_OBSERVATION = "REFRESH_OBSERVATION"
    REOPEN_TARGET = "REOPEN_TARGET"
    RESTART_REVIEW_SESSION = "RESTART_REVIEW_SESSION"
    RESTART_TEST_FIXTURE = "RESTART_TEST_FIXTURE"


class CircuitState(str, Enum):
    """Circuit breaker operational state."""
    CLOSED = "CLOSED"         # Normal operation: recovery permitted
    OPEN = "OPEN"             # Blocked: repeated failures exceeded threshold; halts recovery storms
    HALF_OPEN = "HALF_OPEN"   # Trial: probing one bounded recovery after cooldown


class RecoveryBlockedException(DesktopAutomationException):
    """Raised when recovery is blocked by CircuitBreaker or constitutional policy."""
    pass


@dataclass
class CircuitBreaker:
    """
    Anti-retry-storm circuit breaker.
    Halts repetitive recovery attempts when failure counts exceed the threshold.
    """
    max_consecutive_failures: int = 3
    cooldown_period_sec: float = 10.0
    failure_count: int = 0
    recovery_count: int = 0
    state: CircuitState = CircuitState.CLOSED
    last_failure_time: float = 0.0
    block_reason: Optional[str] = None

    def is_blocked(self, now: Optional[float] = None) -> bool:
        t = now if now is not None else time.time()
        if self.state == CircuitState.OPEN:
            # Check if cooldown period elapsed to enter HALF_OPEN
            if t - self.last_failure_time >= self.cooldown_period_sec:
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker entered HALF_OPEN state (cooldown period elapsed).")
                return False
            return True
        return False

    def record_failure(self, reason: str, now: Optional[float] = None) -> None:
        t = now if now is not None else time.time()
        self.failure_count += 1
        self.last_failure_time = t
        if self.failure_count >= self.max_consecutive_failures:
            self.state = CircuitState.OPEN
            self.block_reason = f"Consecutive failure threshold ({self.max_consecutive_failures}) exceeded: {reason}"
            logger.warning(f"CIRCUIT BREAKER TRIPPED -> OPEN: {self.block_reason}")

    def record_success(self) -> None:
        self.failure_count = 0
        self.recovery_count += 1
        self.state = CircuitState.CLOSED
        self.block_reason = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "state": self.state.value,
            "failure_count": self.failure_count,
            "recovery_count": self.recovery_count,
            "max_consecutive_failures": self.max_consecutive_failures,
            "last_failure_time": self.last_failure_time,
            "block_reason": self.block_reason,
        }


@dataclass(frozen=True)
class RecoveryAttemptRecord:
    """Audit record for a single recovery execution."""
    recovery_id: str
    failure_id: str
    trigger_category: FailureCategory
    action: RecoveryAction
    attempt_number: int
    max_attempts: int
    started_at: float
    duration_ms: float
    result: str                 # "SUCCESS", "FAILED", "CANCELLED", "BLOCKED"
    evidence_refs: List[str] = field(default_factory=list)
    error: Optional[str] = None
    trace_event_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "recovery_id": self.recovery_id,
            "failure_id": self.failure_id,
            "trigger_category": self.trigger_category.value,
            "action": self.action.value,
            "attempt_number": self.attempt_number,
            "max_attempts": self.max_attempts,
            "started_at": self.started_at,
            "duration_ms": self.duration_ms,
            "result": self.result,
            "evidence_refs": list(self.evidence_refs),
            "error": self.error,
        }


class RecoveryPolicy:
    """
    Deterministic recovery policy mapping.
    Enforces that recovery candidates are strictly bounded, scope-preserving,
    and directly tied to verified diagnostic categories.
    """

    POLICY_MAP: Dict[FailureCategory, Tuple[List[RecoveryAction], int]] = {
        FailureCategory.WINDOW_CLOAKED: ([RecoveryAction.REFRESH_OBSERVATION, RecoveryAction.REATTACH], 2),
        FailureCategory.WINDOW_MINIMIZED: ([RecoveryAction.REOPEN_TARGET, RecoveryAction.REATTACH], 2),
        FailureCategory.PROCESS_HANG: ([RecoveryAction.WAIT_FOR_PROCESS], 1),
        FailureCategory.INPUT_DISPATCH_FAILURE: ([RecoveryAction.REFRESH_OBSERVATION, RecoveryAction.REATTACH], 2),
        FailureCategory.SETTLEMENT_TIMEOUT: ([RecoveryAction.REFRESH_OBSERVATION], 2),
        FailureCategory.STATE_NOT_CHANGED: ([RecoveryAction.REFRESH_OBSERVATION], 1),
        FailureCategory.WEBVIEW_ERROR: ([RecoveryAction.RECONNECT, RecoveryAction.WAIT_FOR_WEBVIEW], 2),
        FailureCategory.CONSOLE_EXCEPTION: ([RecoveryAction.REFRESH_OBSERVATION], 1),
        FailureCategory.HARNESS_FAILURE: ([RecoveryAction.RESTART_TEST_FIXTURE], 1),
        FailureCategory.NETWORK_FAILURE: ([RecoveryAction.RECONNECT], 2),
        FailureCategory.TARGET_NOT_FOUND: ([RecoveryAction.REFRESH_OBSERVATION], 1),
        FailureCategory.TARGET_NOT_ACTIONABLE: ([RecoveryAction.REFRESH_OBSERVATION], 2),
    }

    @classmethod
    def get_recovery_candidates(cls, category: FailureCategory) -> List[RecoveryAction]:
        if category in cls.POLICY_MAP:
            return list(cls.POLICY_MAP[category][0])
        return []

    @classmethod
    def get_max_attempts(cls, category: FailureCategory) -> int:
        if category in cls.POLICY_MAP:
            return cls.POLICY_MAP[category][1]
        return 1


class RecoveryEngine:
    """
    Central recovery engine executing bounded recovery operations.
    Preserves original failure in Trace and Evidence before restoration.
    """

    def __init__(self, circuit_breaker: Optional[CircuitBreaker] = None):
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self.recovery_history: List[RecoveryAttemptRecord] = []

    async def execute_recovery(
        self,
        diagnosis: DiagnosticDiagnosis,
        session_state: Any,
        preferred_action: Optional[RecoveryAction] = None,
        timeout_sec: float = 15.0,
    ) -> Tuple[bool, RecoveryAttemptRecord]:
        """
        Executes a bounded recovery operation governed by diagnosis and policy.
        Preserves original failure evidence and emits recovery trace events.
        """
        recovery_id = f"rec_{uuid.uuid4().hex[:10]}"
        failure_id = f"fail_{uuid.uuid4().hex[:8]}"
        category = diagnosis.failure_category
        trace_eng = getattr(session_state, "trace_engine", None)
        start_perf = time.perf_counter()
        started_at = time.time()

        # 1. Check Circuit Breaker
        if self.circuit_breaker.is_blocked():
            record = RecoveryAttemptRecord(
                recovery_id=recovery_id,
                failure_id=failure_id,
                trigger_category=category,
                action=preferred_action or RecoveryAction.REFRESH_OBSERVATION,
                attempt_number=self.circuit_breaker.failure_count,
                max_attempts=self.circuit_breaker.max_consecutive_failures,
                started_at=started_at,
                duration_ms=0.0,
                result="BLOCKED",
                error=self.circuit_breaker.block_reason or "Circuit breaker is OPEN",
            )
            self.recovery_history.append(record)
            raise RecoveryBlockedException(
                f"Recovery is blocked by circuit breaker: {self.circuit_breaker.block_reason}",
                code="RECOVERY_BLOCKED",
                recoverable=False,
            )

        # 2. Select Recovery Action
        allowed_actions = RecoveryPolicy.get_recovery_candidates(category)
        if preferred_action and preferred_action in allowed_actions:
            action_to_run = preferred_action
        elif allowed_actions:
            action_to_run = allowed_actions[0]
        else:
            action_to_run = RecoveryAction.REFRESH_OBSERVATION

        max_attempts = RecoveryPolicy.get_max_attempts(category)

        # 3. Emit Trace: RECOVERY_ATTEMPT (Record original failure before recovery)
        if trace_eng:
            try:
                trace_eng.emit(
                    event_type=DesktopTraceEventType.RECOVERY_ATTEMPT,
                    session_id=session_state.session_id,
                    epoch_id=getattr(session_state, "current_epoch", None),
                    status="ATTEMPTING",
                    details={
                        "recovery_id": recovery_id,
                        "failure_category": category.value,
                        "action": action_to_run.value,
                        "original_root_cause": diagnosis.root_cause_summary,
                    },
                )
            except Exception as e:
                logger.debug(f"Trace emission failed: {e}")

        # 4. Dispatch Recovery Action under timeout budget
        success = False
        error_msg = None
        evidence_refs: List[str] = []

        try:
            success = await asyncio.wait_for(
                self._dispatch_action(action_to_run, session_state),
                timeout=timeout_sec,
            )
        except asyncio.TimeoutError:
            success = False
            error_msg = f"Recovery action '{action_to_run.value}' timed out after {timeout_sec}s."
        except Exception as e:
            success = False
            error_msg = str(e)

        duration_ms = (time.perf_counter() - start_perf) * 1000.0

        # 5. Update Circuit Breaker
        if success:
            self.circuit_breaker.record_success()
        else:
            self.circuit_breaker.record_failure(error_msg or "Recovery action failed")

        # 6. Assemble and Record Recovery Attempt
        record = RecoveryAttemptRecord(
            recovery_id=recovery_id,
            failure_id=failure_id,
            trigger_category=category,
            action=action_to_run,
            attempt_number=self.circuit_breaker.failure_count if not success else 1,
            max_attempts=max_attempts,
            started_at=started_at,
            duration_ms=duration_ms,
            result="SUCCESS" if success else "FAILED",
            evidence_refs=evidence_refs,
            error=error_msg,
        )
        self.recovery_history.append(record)

        # Emit concluding recovery trace event
        if trace_eng:
            try:
                trace_eng.emit(
                    event_type=DesktopTraceEventType.RECOVERY,
                    session_id=session_state.session_id,
                    epoch_id=getattr(session_state, "current_epoch", None),
                    status="SUCCESS" if success else "ERROR",
                    duration_ms=duration_ms,
                    details=record.to_dict(),
                )
            except Exception as e:
                logger.debug(f"Trace recovery status emission failed: {e}")

        return success, record

    async def _dispatch_action(self, action: RecoveryAction, session_state: Any) -> bool:
        """Executes the specific concrete recovery implementation."""
        supervisor = getattr(session_state, "native_supervisor", None)
        target_win = getattr(session_state, "target_window", None)
        target_hwnd = target_win.hwnd if target_win else getattr(session_state, "target_hwnd", None)
        obs_engine = getattr(session_state, "observation_engine", None)
        wv_core = getattr(session_state, "webview_core", None)

        if action == RecoveryAction.REFRESH_OBSERVATION:
            if obs_engine:
                await obs_engine.capture_observation()
                return True
            return True

        elif action == RecoveryAction.REOPEN_TARGET:
            # Restore window from minimized or bring to foreground
            if supervisor and target_hwnd:
                supervisor.restore_window(target_hwnd)
                supervisor.bring_to_foreground(target_hwnd)
                await asyncio.sleep(0.2)
                return True
            return False

        elif action == RecoveryAction.REATTACH:
            # Re-verify window and refresh references
            if supervisor and target_hwnd:
                insp = supervisor.inspect_window(target_hwnd)
                if getattr(insp, "is_visible", False):
                    if obs_engine:
                        await obs_engine.capture_observation()
                    return True
            return False

        elif action == RecoveryAction.WAIT_FOR_PROCESS:
            # Wait for UI thread responsiveness
            if supervisor and target_hwnd:
                for _ in range(5):
                    if not supervisor.is_window_hung(target_hwnd):
                        return True
                    await asyncio.sleep(0.5)
            return False

        elif action == RecoveryAction.WAIT_FOR_WEBVIEW:
            # Wait for CDP endpoint to respond
            if wv_core and hasattr(wv_core, "transport") and wv_core.transport:
                return await wv_core.transport.is_alive()
            return True

        elif action == RecoveryAction.RECONNECT:
            # Reconnect CDP transport
            if wv_core and hasattr(wv_core, "reconnect"):
                return await wv_core.reconnect()
            return True

        elif action == RecoveryAction.RESTART_TEST_FIXTURE:
            # Request fixture reset via harness
            harness = getattr(session_state, "harness_service", None)
            if harness and hasattr(harness, "reset_state"):
                return await harness.reset_state()
            return True

        elif action == RecoveryAction.RESTART_REVIEW_SESSION:
            # Soft reset observation epoch
            if hasattr(session_state, "reference_registry"):
                session_state.reference_registry.advance_epoch()
            return True

        return False
