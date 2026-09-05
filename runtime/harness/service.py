"""
Reviewer Test Harness Service (Architecture H).
Coordinates in-process harness lifecycle, diagnostic ingestion, trace engine
correlation, fixture execution, fault injection, and the Harness Golden Rule.
"""

from __future__ import annotations
import asyncio
import logging
import time
from typing import Dict, List, Optional, Any, Callable, Tuple

from runtime.harness_contracts import (
    HarnessLifecycleSignal,
    HarnessFixtureAction,
    HarnessFaultType,
    HarnessDiagnosticData,
    HarnessFaultInjectionRequest,
    HarnessGoldenRuleEnforcer,
    VerificationVerdict,
    BuildMode,
    HarnessSecurityValidator,
)
from runtime.capability import CapabilityMatrix, CapabilityId, CapabilityStatus, CapabilityCategory
from runtime.trace_engine import DesktopTraceEngine
from runtime.harness.protocol import (
    HarnessMessage,
    HarnessMessageType,
    HarnessMessageValidator,
)
from runtime.harness.transport import HarnessTransportServer

logger = logging.getLogger("desktop_webview.harness.service")


class HarnessService:
    """
    Central coordinator between the Application Harness and the Reviewer Runtime.
    Translates diagnostic timing into Desktop Trace events and supports deterministic settlement.
    """

    def __init__(
        self,
        session_id: str,
        trace_engine: Optional[DesktopTraceEngine] = None,
        capability_matrix: Optional[CapabilityMatrix] = None,
        build_mode: BuildMode = BuildMode.DEV,
        port: int = 0,
        auth_token: Optional[str] = None,
    ):
        # Enforce security boundary upfront
        HarnessSecurityValidator.validate_harness_access(build_mode)

        self.session_id = session_id
        self.trace_engine = trace_engine or DesktopTraceEngine(session_id=session_id)
        self.capability_matrix = capability_matrix
        self.build_mode = build_mode

        self.transport = HarnessTransportServer(
            session_id=session_id,
            port=port,
            auth_token=auth_token,
            on_message=self.handle_incoming_message,
        )

        self.connected_app_id: Optional[str] = None
        self.connected_instance_id: Optional[str] = None
        self.handshake_completed = False
        self.latest_diagnostics: Optional[HarnessDiagnosticData] = None
        self.received_signals: List[Tuple[str, float, Dict[str, Any]]] = []
        self.app_capabilities: Dict[str, str] = {}

        # Signal notification events for waiters
        self._signal_conditions: List[asyncio.Event] = []

    @property
    def auth_token(self) -> str:
        return self.transport.auth_token

    @property
    def endpoint_url(self) -> str:
        return self.transport.endpoint_url

    async def start(self) -> Tuple[str, int]:
        """Starts the underlying transport server and exposes port."""
        res = await self.transport.start()
        logger.info(f"HarnessService running for session {self.session_id} on {self.endpoint_url}")
        return res

    async def stop(self) -> None:
        """Stops the transport server and clears active session state."""
        await self.transport.stop()
        self.handshake_completed = False
        logger.info(f"HarnessService stopped for session {self.session_id}")

    async def handle_incoming_message(self, message: HarnessMessage) -> Dict[str, Any]:
        """Processes and routes an incoming HarnessMessage."""
        mtype = message.message_type

        if mtype == HarnessMessageType.HANDSHAKE:
            return await self._handle_handshake(message)
        elif mtype == HarnessMessageType.LIFECYCLE:
            return await self._handle_lifecycle(message)
        elif mtype == HarnessMessageType.DIAGNOSTICS:
            return await self._handle_diagnostics(message)
        elif mtype == HarnessMessageType.FIXTURE_RESPONSE:
            return await self._handle_fixture_response(message)
        elif mtype == HarnessMessageType.FAULT_RESPONSE:
            return await self._handle_fault_response(message)
        elif mtype == HarnessMessageType.HEALTH_PING:
            return {"status": "PONG", "timestamp": time.time()}
        else:
            return {"status": "IGNORED", "reason": f"Unhandled message type: {mtype}"}

    async def _handle_handshake(self, message: HarnessMessage) -> Dict[str, Any]:
        """Registers the application identity and declares capabilities."""
        self.connected_app_id = message.application_id
        self.connected_instance_id = message.harness_instance_id
        self.handshake_completed = True

        raw_caps = message.payload.get("capabilities", {})
        if isinstance(raw_caps, dict):
            self.app_capabilities = {str(k): str(v) for k, v in raw_caps.items()}

        # Reflect truthful harness capabilities into session CapabilityMatrix if attached
        if self.capability_matrix:
            self.capability_matrix.set_capability(
                CapabilityId.HARNESS_CORE,
                CapabilityStatus.AVAILABLE,
                reason=f"Connected application harness: {message.application_id}",
            )
            self.capability_matrix.set_capability(
                CapabilityId.HARNESS_LIFECYCLE,
                CapabilityStatus.AVAILABLE,
                reason="Harness lifecycle synchronization active",
            )
            self.capability_matrix.set_capability(
                CapabilityId.HARNESS_DIAGNOSTICS,
                CapabilityStatus.AVAILABLE,
                reason="Internal diagnostic telemetry active",
            )
            # Fixtures & Fault injection
            fixtures_status = CapabilityStatus.AVAILABLE if self.app_capabilities.get("fixtures") == "AVAILABLE" else CapabilityStatus.DEGRADED
            self.capability_matrix.set_capability(
                CapabilityId.HARNESS_FIXTURES,
                fixtures_status,
                reason=self.app_capabilities.get("fixtures_reason", "Application fixture handler declared"),
            )
            faults_status = CapabilityStatus.AVAILABLE if self.app_capabilities.get("fault_injection") == "AVAILABLE" else CapabilityStatus.DEGRADED
            self.capability_matrix.set_capability(
                CapabilityId.HARNESS_FAULT_INJECTION,
                faults_status,
                reason=self.app_capabilities.get("fault_reason", "Fault injection capability state declared"),
            )

        # Record in trace
        self.trace_engine.emit(
            event_type=self.trace_engine.record_event.__kwdefaults__["event_type"] if False else "HARNESS_SIGNAL",  # type: ignore
            session_id=self.session_id,
            plane="NATIVE",  # type: ignore
            status="SUCCESS",
            details={
                "source": "harness",
                "trust_class": "diagnostic",
                "event": "HANDSHAKE_COMPLETED",
                "application_id": message.application_id,
                "harness_instance_id": message.harness_instance_id,
                "capabilities": self.app_capabilities,
            },
        )

        return {
            "status": "HANDSHAKE_ACK",
            "session_id": self.session_id,
            "harness_instance_id": self.connected_instance_id,
            "accepted_capabilities": self.app_capabilities,
        }

    async def _handle_lifecycle(self, message: HarnessMessage) -> Dict[str, Any]:
        """Ingests deterministic lifecycle signals."""
        signal = message.payload.get("signal", "UNKNOWN")
        details = message.payload.get("details", {})
        ts = message.timestamp

        self.received_signals.append((signal, ts, details))

        # Ingest directly into Desktop Trace
        self.trace_engine.ingest_harness_event(
            signal_or_telemetry=signal,
            session_id=self.session_id,
            is_signal=True,
            details=details,
        )

        # Notify any settlement waiters
        for cond in list(self._signal_conditions):
            cond.set()

        return {"status": "RECORDED", "signal": signal, "timestamp": ts}

    async def _handle_diagnostics(self, message: HarnessMessage) -> Dict[str, Any]:
        """Ingests structured application state diagnostics."""
        diag_dict = message.payload.get("diagnostics", {})
        active_ops = [str(x) for x in diag_dict.get("active_operations", [])]
        durations = {str(k): float(v) for k, v in diag_dict.get("operation_duration_ms", {}).items()}
        errors = [str(e) for e in diag_dict.get("internal_errors", [])]

        diag_data = HarnessDiagnosticData(
            current_screen=diag_dict.get("current_screen"),
            current_route=diag_dict.get("current_route"),
            active_operations=active_ops,
            operation_duration_ms=durations,
            internal_errors=errors,
            pending_operations_count=int(diag_dict.get("pending_operations_count", 0)),
            timestamp=message.timestamp,
        )
        self.latest_diagnostics = diag_data

        # Ingest into trace
        self.trace_engine.ingest_harness_event(
            signal_or_telemetry="DIAGNOSTIC_UPDATE",
            session_id=self.session_id,
            is_signal=False,
            details=diag_data.to_dict(),
        )

        return {"status": "RECORDED", "timestamp": message.timestamp}

    async def _handle_fixture_response(self, message: HarnessMessage) -> Dict[str, Any]:
        self.trace_engine.ingest_harness_event(
            signal_or_telemetry="FIXTURE_RESPONSE",
            session_id=self.session_id,
            is_signal=False,
            details=message.payload,
        )
        return {"status": "ACK"}

    async def _handle_fault_response(self, message: HarnessMessage) -> Dict[str, Any]:
        self.trace_engine.ingest_harness_event(
            signal_or_telemetry="FAULT_RESPONSE",
            session_id=self.session_id,
            is_signal=False,
            details=message.payload,
        )
        return {"status": "ACK"}

    def check_signal(self, predicate: Callable[[str], bool]) -> Optional[str]:
        """Checks if any received lifecycle signal satisfies the given predicate."""
        for sig, _, _ in reversed(self.received_signals):
            if predicate(sig):
                return sig
        return None

    def reconcile_with_physical_reality(
        self,
        physical_reality_verdict: VerificationVerdict,
        harness_signal: Optional[HarnessLifecycleSignal] = None,
    ) -> VerificationVerdict:
        """
        Applies the Harness Golden Rule:
        Black-Box Reality Validation outranks Instrumented Diagnosis.
        """
        return HarnessGoldenRuleEnforcer.reconcile_verdict(
            physical_reality_verdict=physical_reality_verdict,
            harness_signal=harness_signal,
            harness_diagnostics=self.latest_diagnostics,
        )
