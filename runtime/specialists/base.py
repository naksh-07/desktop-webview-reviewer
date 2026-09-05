"""
Base Subordinate Specialist Runtime (Architecture H).
Implements the core boundary enforcement, lifecycle management,
tool authorization gate, deadline propagation, cancellation handling,
and untrusted observation isolation for all specialist subagents.
"""

from __future__ import annotations
import asyncio
import hashlib
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Set, Any, Callable, Coroutine

from runtime.specialist_contracts import (
    SpecialistRole,
    SpecialistContract,
    SpecialistRegistry,
)
from runtime.specialist_models import (
    SpecialistLifecycleState,
    SpecialistResultStatus,
    SpecialistDelegation,
    ToolAuditRecord,
    SpecialistResult,
)
from runtime.trace_models import (
    DesktopTraceEventType,
    TraceCorrelation,
)
from runtime.trace_engine import redact_sensitive_trace_payload
from runtime.errors import DesktopAutomationException

logger = logging.getLogger("desktop_webview.specialist")


class SpecialistSecurityException(DesktopAutomationException):
    """Raised when a specialist attempts an unauthorized or out-of-scope operation."""
    pass


class SpecialistTimeoutException(DesktopAutomationException):
    """Raised when specialist execution or a child tool exceeds its delegated deadline."""
    pass


class SpecialistCancelledException(DesktopAutomationException):
    """Raised when specialist execution is explicitly cancelled."""
    pass


class BaseSpecialistRuntime(ABC):
    """
    Framework-neutral execution container for a subordinate specialist.
    Enforces the Anti-God-Agent rule at runtime.
    """

    def __init__(
        self,
        delegation: SpecialistDelegation,
        session_state: Any,
        parent_trace_engine: Optional[Any] = None,
    ):
        self.delegation = delegation
        self.session_state = session_state
        self.specialist_id = f"spec_{self.role.value.lower()}_{uuid.uuid4().hex[:8]}"
        self.contract: SpecialistContract = SpecialistRegistry.get_contract(self.role)
        self.trace_engine = parent_trace_engine or getattr(session_state, "trace_engine", None)

        self.current_state = SpecialistLifecycleState.DELEGATED
        self.audit_records: List[ToolAuditRecord] = []
        self.tools_used: Set[str] = set()
        self.lifecycle_history: List[Dict[str, Any]] = []
        self.started_at: Optional[float] = None
        self.completed_at: Optional[float] = None
        self._cancellation_requested = False

        self._record_lifecycle(SpecialistLifecycleState.DELEGATED, "Specialist instance initialized.")

    @property
    @abstractmethod
    def role(self) -> SpecialistRole:
        """The canonical role fulfilled by this specialist runtime."""
        raise NotImplementedError

    def request_cancellation(self) -> None:
        """Signals graceful cancellation to the specialist."""
        self._cancellation_requested = True
        logger.info(f"Cancellation requested for specialist {self.specialist_id} ({self.role.value})")

    def is_cancelled(self) -> bool:
        return self._cancellation_requested

    def check_deadline(self) -> None:
        """Checks if the delegation deadline has passed."""
        if self.delegation.is_expired():
            self._record_lifecycle(SpecialistLifecycleState.TIMED_OUT, "Delegation deadline exceeded.")
            raise SpecialistTimeoutException(
                f"Specialist {self.specialist_id} exceeded deadline {self.delegation.deadline:.2f}",
                code="SPECIALIST_TIMEOUT",
                recoverable=True,
            )

    def _record_lifecycle(self, state: SpecialistLifecycleState, reason: str = "") -> None:
        """Transitions state, updates history, and emits Desktop Trace event."""
        self.current_state = state
        entry = {
            "state": state.value,
            "timestamp": time.time(),
            "reason": reason,
        }
        self.lifecycle_history.append(entry)

        if self.trace_engine:
            try:
                self.trace_engine.emit(
                    event_type=DesktopTraceEventType.SPECIALIST_LIFECYCLE,
                    session_id=self.delegation.scope.session_id,
                    epoch_id=getattr(self.session_state, "current_epoch", None),
                    action_id=self.delegation.parent_action_id,
                    status="SUCCESS" if not state.is_terminal or state == SpecialistLifecycleState.COMPLETED else "ERROR",
                    details={
                        "specialist_id": self.specialist_id,
                        "role": self.role.value,
                        "delegation_id": self.delegation.delegation_id,
                        "lifecycle_state": state.value,
                        "reason": reason,
                    },
                )
            except Exception as e:
                logger.debug(f"Failed to emit trace event for specialist lifecycle: {e}")

    # -------------------------------------------------------------------------
    # Untrusted Application Observation Barrier
    # -------------------------------------------------------------------------
    @staticmethod
    def sanitize_untrusted_content(raw_data: Any) -> Any:
        """
        Guarantees application-originated text (DOM strings, logs, console lines,
        harness payloads) remains untrusted data and cannot inject specialist directives.
        """
        if isinstance(raw_data, str):
            # Redact secrets and truncate unbounded blobs
            clean = redact_sensitive_trace_payload(raw_data)
            return clean[:5000]
        if isinstance(raw_data, dict):
            return {str(k): BaseSpecialistRuntime.sanitize_untrusted_content(v) for k, v in raw_data.items()}
        if isinstance(raw_data, (list, tuple)):
            return [BaseSpecialistRuntime.sanitize_untrusted_content(x) for x in raw_data]
        return raw_data

    # -------------------------------------------------------------------------
    # Tool Authorization and Invocation Gate
    # -------------------------------------------------------------------------
    async def invoke_tool(
        self,
        tool_name: str,
        tool_fn: Callable[..., Coroutine[Any, Any, Any]],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Authorized execution gate for specialist tool calls.
        Enforces permitted_tools, read-only boundary, deadline checks, and tool auditing.
        """
        self.check_deadline()
        if self._cancellation_requested:
            self._record_lifecycle(SpecialistLifecycleState.CANCELLED, "Execution cancelled before tool call.")
            raise SpecialistCancelledException(f"Specialist {self.specialist_id} was cancelled.")

        # 1. Validate tool in delegation's permitted_tools
        if tool_name not in self.delegation.permitted_tools:
            record = ToolAuditRecord(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                tool=tool_name,
                timestamp=time.time(),
                duration_ms=0.0,
                arguments_digest=hashlib.sha256(str(kwargs).encode()).hexdigest()[:16],
                authorization_result="REJECTED_UNPERMITTED_TOOL",
                result_status="ERROR",
                error=f"Tool '{tool_name}' is not in delegation permitted_tools: {sorted(list(self.delegation.permitted_tools))}",
            )
            self.audit_records.append(record)
            self._emit_tool_audit_trace(record)
            raise SpecialistSecurityException(
                f"Specialist '{self.role.value}' denied access to tool '{tool_name}'. Not permitted in delegation.",
                code="SPECIALIST_TOOL_FORBIDDEN",
                recoverable=False,
            )

        # 2. Validate tool in canonical role contract
        if not self.contract.validate_tool_access(tool_name):
            record = ToolAuditRecord(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                tool=tool_name,
                timestamp=time.time(),
                duration_ms=0.0,
                arguments_digest=hashlib.sha256(str(kwargs).encode()).hexdigest()[:16],
                authorization_result="REJECTED_ROLE_CONTRACT_VIOLATION",
                result_status="ERROR",
                error=f"Tool '{tool_name}' violates contract for role {self.role.value}",
            )
            self.audit_records.append(record)
            self._emit_tool_audit_trace(record)
            raise SpecialistSecurityException(
                f"Specialist '{self.role.value}' denied access to tool '{tool_name}'. Violates role contract.",
                code="SPECIALIST_CONTRACT_VIOLATION",
                recoverable=False,
            )

        # 3. Read-only role protection
        if self.contract.is_read_only and self._is_state_modifying_tool(tool_name):
            record = ToolAuditRecord(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                tool=tool_name,
                timestamp=time.time(),
                duration_ms=0.0,
                arguments_digest=hashlib.sha256(str(kwargs).encode()).hexdigest()[:16],
                authorization_result="REJECTED_MUTATION_FORBIDDEN",
                result_status="ERROR",
                error=f"Role {self.role.value} is read-only; mutation via '{tool_name}' is strictly prohibited.",
            )
            self.audit_records.append(record)
            self._emit_tool_audit_trace(record)
            raise SpecialistSecurityException(
                f"Role {self.role.value} is read-only. Tool '{tool_name}' causes state mutation.",
                code="SPECIALIST_MUTATION_FORBIDDEN",
                recoverable=False,
            )

        # Record tool usage
        self.tools_used.add(tool_name)
        start_time = time.perf_counter()
        arg_summary = {k: str(v)[:100] for k, v in kwargs.items()}
        arg_digest = hashlib.sha256(json.dumps(arg_summary, sort_keys=True).encode()).hexdigest()[:16]

        try:
            # Execute the tool with deadline propagation
            remaining_time = self.delegation.get_remaining_timeout()
            res = await asyncio.wait_for(tool_fn(*args, **kwargs), timeout=remaining_time)
            duration_ms = (time.perf_counter() - start_time) * 1000.0

            record = ToolAuditRecord(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                tool=tool_name,
                timestamp=time.time(),
                duration_ms=duration_ms,
                arguments_digest=arg_digest,
                authorization_result="AUTHORIZED",
                result_status="SUCCESS",
            )
            self.audit_records.append(record)
            self._emit_tool_audit_trace(record)
            return res

        except asyncio.TimeoutError:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            record = ToolAuditRecord(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                tool=tool_name,
                timestamp=time.time(),
                duration_ms=duration_ms,
                arguments_digest=arg_digest,
                authorization_result="AUTHORIZED",
                result_status="ERROR",
                error=f"Tool call '{tool_name}' exceeded timeout budget",
            )
            self.audit_records.append(record)
            self._emit_tool_audit_trace(record)
            raise SpecialistTimeoutException(f"Tool call '{tool_name}' timed out after {duration_ms:.1f}ms")

        except Exception as e:
            duration_ms = (time.perf_counter() - start_time) * 1000.0
            record = ToolAuditRecord(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                tool=tool_name,
                timestamp=time.time(),
                duration_ms=duration_ms,
                arguments_digest=arg_digest,
                authorization_result="AUTHORIZED",
                result_status="ERROR",
                error=str(e),
            )
            self.audit_records.append(record)
            self._emit_tool_audit_trace(record)
            raise

    def _is_state_modifying_tool(self, tool_name: str) -> bool:
        """Determines if a tool performs state-modifying action dispatch."""
        mutating_tools = {
            "desktop_click",
            "desktop_type",
            "desktop_press_key",
            "desktop_hover",
            "desktop_scroll",
            "desktop_drag_drop",
            "desktop_launch",
        }
        return tool_name in mutating_tools

    def _emit_tool_audit_trace(self, record: ToolAuditRecord) -> None:
        """Emits a structured audit trace event."""
        if self.trace_engine:
            try:
                self.trace_engine.emit(
                    event_type=DesktopTraceEventType.SPECIALIST_TOOL_AUDIT,
                    session_id=self.delegation.scope.session_id,
                    epoch_id=getattr(self.session_state, "current_epoch", None),
                    action_id=self.delegation.parent_action_id,
                    status=record.result_status,
                    duration_ms=record.duration_ms,
                    details=record.to_dict(),
                )
            except Exception as e:
                logger.debug(f"Failed to emit tool audit trace: {e}")

    # -------------------------------------------------------------------------
    # Execution Template
    # -------------------------------------------------------------------------
    async def run(self) -> SpecialistResult:
        """
        Deterministic execution template:
        DELEGATED -> VALIDATING -> RUNNING -> OBSERVING/ACTING -> COLLECTING_RESULT -> COMPLETED
        """
        self.started_at = time.time()
        start_perf = time.perf_counter()

        try:
            # 1. VALIDATING
            self._record_lifecycle(SpecialistLifecycleState.VALIDATING, "Validating delegation parameters and session.")
            current_epoch = getattr(self.session_state, "current_epoch", None)
            target_proc = getattr(self.session_state, "target_process", None)
            current_pid = target_proc.pid if target_proc else None

            rejections = self.delegation.validate(
                current_session_id=self.session_state.session_id,
                current_epoch=current_epoch,
                current_pid=current_pid,
            )
            if rejections:
                self._record_lifecycle(SpecialistLifecycleState.REJECTED, "; ".join(rejections))
                return SpecialistResult(
                    specialist_id=self.specialist_id,
                    role=self.role,
                    delegation_id=self.delegation.delegation_id,
                    session_id=self.session_state.session_id,
                    status=SpecialistResultStatus.REJECTED,
                    answer="Delegation rejected by validation gate.",
                    errors=rejections,
                    confidence=1.0,
                    duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                    tools_used=list(self.tools_used),
                    lifecycle_history=list(self.lifecycle_history),
                )

            # 2. RUNNING
            self._record_lifecycle(SpecialistLifecycleState.RUNNING, "Starting specialist execution.")

            # Delegate to subclass
            result = await self.execute()

            # 3. COLLECTING_RESULT & COMPLETED
            self._record_lifecycle(SpecialistLifecycleState.COLLECTING_RESULT, "Assembling result envelope.")
            result.duration_ms = (time.perf_counter() - start_perf) * 1000.0
            result.tools_used = sorted(list(self.tools_used))
            result.lifecycle_history = list(self.lifecycle_history)
            self._record_lifecycle(SpecialistLifecycleState.COMPLETED, f"Result status: {result.status.value}")
            return result

        except SpecialistTimeoutException as e:
            self._record_lifecycle(SpecialistLifecycleState.TIMED_OUT, str(e))
            return SpecialistResult(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                session_id=self.session_state.session_id,
                status=SpecialistResultStatus.TIMED_OUT,
                answer=f"Execution timed out: {e}",
                errors=[str(e)],
                confidence=1.0,
                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                tools_used=list(self.tools_used),
                lifecycle_history=list(self.lifecycle_history),
            )

        except SpecialistCancelledException as e:
            self._record_lifecycle(SpecialistLifecycleState.CANCELLED, str(e))
            return SpecialistResult(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                session_id=self.session_state.session_id,
                status=SpecialistResultStatus.CANCELLED,
                answer=f"Execution cancelled: {e}",
                errors=[str(e)],
                confidence=1.0,
                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                tools_used=list(self.tools_used),
                lifecycle_history=list(self.lifecycle_history),
            )

        except SpecialistSecurityException as e:
            self._record_lifecycle(SpecialistLifecycleState.REJECTED, str(e))
            return SpecialistResult(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                session_id=self.session_state.session_id,
                status=SpecialistResultStatus.REJECTED,
                answer=f"Security rejection: {e}",
                errors=[str(e)],
                confidence=1.0,
                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                tools_used=list(self.tools_used),
                lifecycle_history=list(self.lifecycle_history),
            )

        except Exception as e:
            logger.exception(f"Specialist {self.specialist_id} failed with unhandled exception: {e}")
            self._record_lifecycle(SpecialistLifecycleState.FAILED, str(e))
            return SpecialistResult(
                specialist_id=self.specialist_id,
                role=self.role,
                delegation_id=self.delegation.delegation_id,
                session_id=self.session_state.session_id,
                status=SpecialistResultStatus.FAILED,
                answer=f"Execution failure: {e}",
                errors=[str(e)],
                confidence=0.0,
                duration_ms=(time.perf_counter() - start_perf) * 1000.0,
                tools_used=list(self.tools_used),
                lifecycle_history=list(self.lifecycle_history),
            )

    @abstractmethod
    async def execute(self) -> SpecialistResult:
        """Subclass implementation of the specialist's specific mandate."""
        raise NotImplementedError
