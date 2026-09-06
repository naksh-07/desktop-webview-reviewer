"""
Lifecycle and Update System Data Models.

Defines:
- LifecycleState enum
- InstallationStateRecord (persistent state record)
- UpdateCheckResult (update availability & channel)
- SkillSyncStatus (skill / runtime compatibility)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class LifecycleState(str, Enum):
    """Product installation & update lifecycle states."""

    INSTALLED = "INSTALLED"
    UPDATE_AVAILABLE = "UPDATE_AVAILABLE"
    UP_TO_DATE = "UP_TO_DATE"
    UPDATED = "UPDATED"
    PINNED = "PINNED"
    ROLLBACK_AVAILABLE = "ROLLBACK_AVAILABLE"
    DEGRADED = "DEGRADED"
    INCOMPATIBLE = "INCOMPATIBLE"
    CHECK_UNAVAILABLE = "CHECK_UNAVAILABLE"


@dataclass
class InstallationStateRecord:
    """
    Persistent installation registry record.
    Stored at ~/.desktop_webview_reviewer/installation_state.json.
    Never stores tokens, credentials, or secrets.
    """

    installed_version: str
    previous_known_good_version: Optional[str] = None
    pinned_version: Optional[str] = None
    channel: str = "stable"
    installation_timestamp: str = ""
    last_successful_validation: str = ""
    runtime_location: str = ""
    package_identity: str = "desktop-webview-reviewer"
    last_update_attempt: Optional[str] = None
    last_update_status: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InstallationStateRecord:
        return cls(
            installed_version=data.get("installed_version", "2.0.0"),
            previous_known_good_version=data.get("previous_known_good_version"),
            pinned_version=data.get("pinned_version"),
            channel=data.get("channel", "stable"),
            installation_timestamp=data.get("installation_timestamp", ""),
            last_successful_validation=data.get("last_successful_validation", ""),
            runtime_location=data.get("runtime_location", ""),
            package_identity=data.get("package_identity", "desktop-webview-reviewer"),
            last_update_attempt=data.get("last_update_attempt"),
            last_update_status=data.get("last_update_status"),
        )


@dataclass
class UpdateCandidate:
    """A release candidate discovered from GitHub Releases."""

    version: str
    tag_name: str
    release_name: str
    release_notes: str
    published_at: str
    prerelease: bool = False
    download_url: Optional[str] = None
    tarball_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class UpdateCheckResult:
    """Structured response from update check."""

    installed_version: str
    latest_compatible_version: Optional[str]
    update_available: bool
    state: LifecycleState
    channel: str = "stable"
    pinned_version: Optional[str] = None
    release_notes: Optional[str] = None
    published_at: Optional[str] = None
    details: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["state"] = self.state.value
        return d


@dataclass
class SkillSyncStatus:
    """Status of the installed Antigravity skill package."""

    skill_path: Optional[str]
    skill_version: Optional[str]
    compatible_runtime_range: Optional[str]
    runtime_version: str
    is_compatible: bool
    skill_update_required: bool
    runtime_update_required: bool
    diagnosis: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorCheckResult:
    """Individual doctor check result."""

    name: str
    status: str  # PASS / FAIL / WARN
    message: str
    details: Optional[Dict[str, Any]] = None


@dataclass
class DoctorReport:
    """Overall report from update doctor."""

    passed: bool
    installed_version: str
    runtime_location: str
    checks: List[DoctorCheckResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "installed_version": self.installed_version,
            "runtime_location": self.runtime_location,
            "checks": [asdict(c) for c in self.checks],
        }
