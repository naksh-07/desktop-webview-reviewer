"""
Product Lifecycle, Versioning, Update, Pinning, and Rollback Subsystem.

Architecture H Compliant.
Preserves the frozen 12-tool MCP interface while providing robust,
fail-closed operational lifecycle for long-term installation maintainability.
"""

from .models import (
    DoctorCheckResult,
    DoctorReport,
    InstallationStateRecord,
    LifecycleState,
    SkillSyncStatus,
    UpdateCandidate,
    UpdateCheckResult,
)
from .registry import InstallationRegistry, get_state_file_path
from .github_client import GitHubReleasesClient
from .skill_sync import SkillSynchronizer
from .updater import LifecycleUpdater
from .doctor import LifecycleDoctor

__all__ = [
    "LifecycleState",
    "InstallationStateRecord",
    "UpdateCandidate",
    "UpdateCheckResult",
    "SkillSyncStatus",
    "DoctorCheckResult",
    "DoctorReport",
    "InstallationRegistry",
    "get_state_file_path",
    "GitHubReleasesClient",
    "SkillSynchronizer",
    "LifecycleUpdater",
    "LifecycleDoctor",
]
