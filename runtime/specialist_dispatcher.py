"""
Specialist Dispatcher & Subordination Gateway (Architecture H / Phase 15).
Coordinates the execution of explicitly delegated specialist subagents.
Enforces the Controller Authority Boundary: executes delegated HOW tasks
without autonomous mission expansion or strategy generation.
"""

from __future__ import annotations
import asyncio
import logging
from typing import Dict, List, Optional, Any

from runtime.specialist_contracts import SpecialistRole
from runtime.specialist_models import (
    SpecialistDelegation,
    SpecialistResult,
    SpecialistResultStatus,
)
from runtime.specialists import (
    ExplorerSpecialist,
    TesterSpecialist,
    RealityInspectorSpecialist,
    DebuggerSpecialist,
    EvidenceSpecialist,
)
from runtime.errors import SessionNotFoundException

logger = logging.getLogger("desktop_webview.specialist_dispatcher")


class SpecialistDispatcher:
    """
    Subordinate specialist gateway.
    Receives explicit delegations from the controlling orchestrator,
    validates parameters, routes to the bounded specialist runtime,
    and returns authoritative structured results.
    """

    def __init__(self, session_manager: Optional[Any] = None):
        self.session_manager = session_manager
        self._active_specialists: Dict[str, Any] = {}

    def get_specialist_class(self, role: SpecialistRole) -> type:
        """Resolves the canonical implementation class for a specialist role."""
        mapping = {
            SpecialistRole.EXPLORER: ExplorerSpecialist,
            SpecialistRole.TESTER: TesterSpecialist,
            SpecialistRole.REALITY_INSPECTOR: RealityInspectorSpecialist,
            SpecialistRole.DEBUGGER: DebuggerSpecialist,
            SpecialistRole.EVIDENCE_SPECIALIST: EvidenceSpecialist,
        }
        if role not in mapping:
            raise ValueError(f"Unknown specialist role: {role}")
        return mapping[role]

    async def dispatch(
        self,
        delegation: SpecialistDelegation,
        session_state: Optional[Any] = None,
    ) -> SpecialistResult:
        """
        Executes an explicitly delegated specialist assignment.
        Validates session boundaries, propagates deadlines, and enforces role contracts.
        """
        session_id = delegation.scope.session_id

        # 1. Resolve SessionState
        resolved_session = session_state
        if resolved_session is None and self.session_manager is not None:
            try:
                resolved_session = self.session_manager.get_session(session_id)
            except SessionNotFoundException as e:
                return SpecialistResult(
                    specialist_id="none",
                    role=delegation.role,
                    delegation_id=delegation.delegation_id,
                    session_id=session_id,
                    status=SpecialistResultStatus.REJECTED,
                    answer=f"Delegation rejected: session '{session_id}' not found.",
                    errors=[str(e)],
                    confidence=1.0,
                )

        if resolved_session is None:
            return SpecialistResult(
                specialist_id="none",
                role=delegation.role,
                delegation_id=delegation.delegation_id,
                session_id=session_id,
                status=SpecialistResultStatus.REJECTED,
                answer=f"Delegation rejected: no active session available for '{session_id}'.",
                errors=["SessionState is None"],
                confidence=1.0,
            )

        if getattr(resolved_session, "is_closed", False):
            return SpecialistResult(
                specialist_id="none",
                role=delegation.role,
                delegation_id=delegation.delegation_id,
                session_id=session_id,
                status=SpecialistResultStatus.REJECTED,
                answer=f"Delegation rejected: session '{session_id}' is terminated/closed.",
                errors=["Session is closed or terminated"],
                confidence=1.0,
            )

        # 2. Instantiate Specialist
        specialist_cls = self.get_specialist_class(delegation.role)
        specialist = specialist_cls(delegation=delegation, session_state=resolved_session)
        self._active_specialists[specialist.specialist_id] = specialist

        # 3. Execute under bounded timeout budget
        try:
            remaining_timeout = delegation.get_remaining_timeout()
            if remaining_timeout <= 0:
                return SpecialistResult(
                    specialist_id=specialist.specialist_id,
                    role=delegation.role,
                    delegation_id=delegation.delegation_id,
                    session_id=session_id,
                    status=SpecialistResultStatus.TIMED_OUT,
                    answer="Delegation expired before execution commenced.",
                    errors=["Delegation deadline in the past"],
                    confidence=1.0,
                )

            result = await specialist.run()
            return result

        finally:
            self._active_specialists.pop(specialist.specialist_id, None)

    def cancel_specialist(self, specialist_id: str) -> bool:
        """Requests graceful cancellation of an in-flight specialist."""
        spec = self._active_specialists.get(specialist_id)
        if spec:
            spec.request_cancellation()
            return True
        return False
