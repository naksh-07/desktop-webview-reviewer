"""
Antigravity Experience Integration and Correlation Package.

Provides isolated integration surface for:
- Normalized agent event envelopes and contracts
- Zero-knowledge privacy boundary and argument sanitization
- Relational correlation between Antigravity agent activity and DWR reality
- Lifecycle hook adapters for official Antigravity hooks
- Diagnostic status reporting
"""

from runtime.experience.antigravity.contracts import (
    AgentEventEnvelope,
    AgentEventType,
    CorrelationConfidence,
    UserCorrectionType,
)
from runtime.experience.antigravity.models import (
    AgentArtifactRecord,
    AgentCorrectionRecord,
    AgentDwrCorrelationRecord,
    AgentSessionRecord,
    AgentSubagentRecord,
    AgentToolCallRecord,
    AgentTurnRecord,
    AntigravityBridgeStatus,
)
from runtime.experience.antigravity.sanitizer import (
    AgentEventSanitizer,
    AgentEventSanitizationException,
)
from runtime.experience.antigravity.correlator import (
    AgentDwrCorrelator,
)
from runtime.experience.antigravity.hook_adapter import (
    AntigravityHookAdapter,
)
from runtime.experience.antigravity.bridge import (
    AntigravityCorrelationBridge,
)

__all__ = [
    "AgentEventType",
    "CorrelationConfidence",
    "UserCorrectionType",
    "AgentEventEnvelope",
    "AgentSessionRecord",
    "AgentTurnRecord",
    "AgentToolCallRecord",
    "AgentSubagentRecord",
    "AgentArtifactRecord",
    "AgentCorrectionRecord",
    "AgentDwrCorrelationRecord",
    "AntigravityBridgeStatus",
    "AgentEventSanitizer",
    "AgentEventSanitizationException",
    "AgentDwrCorrelator",
    "AntigravityHookAdapter",
    "AntigravityCorrelationBridge",
]
