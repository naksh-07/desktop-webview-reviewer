"""
Reviewer Test Harness Contracts & Security Boundary (Architecture H).
Defines lifecycle signals, diagnostics, test fixtures, fault injection,
the Harness Golden Rule enforcer, and the Release CI Security Gate.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Any

from runtime.evidence_models import VerificationVerdict


class HarnessLifecycleSignal(str, Enum):
    """Deterministic in-process lifecycle timing signals emitted by the test harness."""
    APP_STARTING = "APP_STARTING"
    APP_READY = "APP_READY"
    SCREEN_READY = "SCREEN_READY"
    DATA_READY = "DATA_READY"
    SAVE_STARTED = "SAVE_STARTED"
    SAVE_COMPLETED = "SAVE_COMPLETED"
    NAVIGATION_STARTED = "NAVIGATION_STARTED"
    NAVIGATION_COMPLETED = "NAVIGATION_COMPLETED"


class HarnessFixtureAction(str, Enum):
    """Test fixture orchestration operations."""
    SEED_DATA = "SEED_DATA"
    RESET_STATE = "RESET_STATE"
    CREATE_FIXTURE = "CREATE_FIXTURE"
    CLEAR_FIXTURE = "CLEAR_FIXTURE"


class HarnessFaultType(str, Enum):
    """Simulated fault injection types for chaos and resilience testing."""
    NETWORK_DELAY = "NETWORK_DELAY"
    NETWORK_FAILURE = "NETWORK_FAILURE"
    DATABASE_FAILURE = "DATABASE_FAILURE"
    TIMEOUT = "TIMEOUT"
    RENDER_DELAY = "RENDER_DELAY"
    PERMISSION_FAILURE = "PERMISSION_FAILURE"
    SIMULATED_CRASH = "SIMULATED_CRASH"


class BuildMode(str, Enum):
    """Target binary build classification."""
    DEV_OR_REVIEW = "DEV_OR_REVIEW"
    RELEASE_PRODUCTION = "RELEASE_PRODUCTION"


class HarnessSecurityViolationException(Exception):
    """Raised when harness capabilities are accessed in or targeted at a release build."""
    pass


class HarnessGoldenRuleViolationException(Exception):
    """Raised when a harness signal attempts to illegitimately override a physical verification failure."""
    pass


@dataclass(frozen=True)
class HarnessDiagnosticData:
    """Internal diagnostic telemetry captured from the test harness."""
    current_screen: Optional[str] = None
    current_route: Optional[str] = None
    active_operations: List[str] = field(default_factory=list)
    operation_duration_ms: Dict[str, float] = field(default_factory=dict)
    internal_errors: List[str] = field(default_factory=list)
    pending_operations_count: int = 0
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "current_screen": self.current_screen,
            "current_route": self.current_route,
            "active_operations": self.active_operations,
            "operation_duration_ms": self.operation_duration_ms,
            "internal_errors": self.internal_errors,
            "pending_operations_count": self.pending_operations_count,
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class HarnessFaultInjectionRequest:
    """Fault injection directive passed to development build harness."""
    fault_type: HarnessFaultType
    target_subsystem: str
    duration_ms: int = 1000
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fault_type": self.fault_type.value if isinstance(self.fault_type, HarnessFaultType) else str(self.fault_type),
            "target_subsystem": self.target_subsystem,
            "duration_ms": self.duration_ms,
            "parameters": self.parameters,
        }


class HarnessSecurityValidator:
    """
    Security gate verifying that harness communication is completely disabled
    and rejected in production release builds.
    """

    @staticmethod
    def validate_harness_access(build_mode: BuildMode) -> bool:
        """
        Guarantees that harness capabilities cannot be invoked in RELEASE_PRODUCTION mode.
        """
        if build_mode == BuildMode.RELEASE_PRODUCTION:
            raise HarnessSecurityViolationException(
                "SECURITY VIOLATION: Reviewer Test Harness is strictly forbidden in RELEASE_PRODUCTION builds. "
                "Harness capabilities, test endpoints, and fault injection must be physically stripped from release artifacts."
            )
        return True


class HarnessGoldenRuleEnforcer:
    """
    Enforces the Harness Golden Rule:
    The harness is supporting evidence; it must NEVER become the authoritative source of user-facing success.
    Black-Box Reality Validation outranks Instrumented Diagnosis.
    """

    @staticmethod
    def reconcile_verdict(
        physical_reality_verdict: VerificationVerdict,
        harness_signal: Optional[HarnessLifecycleSignal] = None,
        harness_diagnostics: Optional[HarnessDiagnosticData] = None,
    ) -> VerificationVerdict:
        """
        Reconciles physical reality verification with harness telemetry.
        If physical reality is FAIL or UNVERIFIED, the final verdict remains FAIL or UNVERIFIED
        regardless of positive signals reported by the harness.
        """
        # If physical reality explicitly failed, harness cannot rescue it
        if physical_reality_verdict == VerificationVerdict.FAIL:
            return VerificationVerdict.FAIL

        # If physical reality could not verify the outcome (e.g. window cloaked or unrendered),
        # positive harness signal only provides diagnostic context, NOT a PASS verdict.
        if physical_reality_verdict == VerificationVerdict.UNVERIFIED:
            return VerificationVerdict.UNVERIFIED

        # If physical reality verified the outcome as PASS, harness telemetry provides supporting proof.
        return VerificationVerdict.PASS
