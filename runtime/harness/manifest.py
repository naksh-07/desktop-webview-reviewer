"""
Integration Manifest for Reviewer Test Harness (Architecture H).
Maintains an immutable, machine-readable audit trail of all Reviewer-specific
files, surgical modifications, markers, and reversal metadata introduced into a project.
"""

from __future__ import annotations
import hashlib
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

MANIFEST_FILENAME = ".reviewer_harness.json"
CURRENT_HARNESS_VERSION = "1.0.0"


@dataclass
class ModifiedFileRecord:
    """Record of a surgical modification applied to an existing project file."""
    path: str
    original_sha256: str
    modified_sha256: str
    markers: List[str]
    injected_snippet: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "original_sha256": self.original_sha256,
            "modified_sha256": self.modified_sha256,
            "markers": self.markers,
            "injected_snippet": self.injected_snippet,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ModifiedFileRecord:
        return cls(
            path=data["path"],
            original_sha256=data["original_sha256"],
            modified_sha256=data["modified_sha256"],
            markers=data.get("markers", []),
            injected_snippet=data.get("injected_snippet", ""),
        )


@dataclass
class IntegrationManifest:
    """
    Audit record tracking all Reviewer Harness integrations.
    Provides cryptographic reversal metadata to guarantee clean uninstallation.
    """
    project: str
    framework: str
    adapter: str
    harness_version: str = CURRENT_HARNESS_VERSION
    integration_mode: str = "DEV_OR_REVIEW"
    created_at: float = field(default_factory=time.time)
    files_added: List[str] = field(default_factory=list)
    files_modified: List[ModifiedFileRecord] = field(default_factory=list)
    development_only_markers: List[str] = field(default_factory=list)
    capabilities: Dict[str, str] = field(default_factory=dict)
    validation_status: str = "VALIDATED"
    reversal_metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project": self.project,
            "framework": self.framework,
            "adapter": self.adapter,
            "harness_version": self.harness_version,
            "integration_mode": self.integration_mode,
            "created_at": self.created_at,
            "files_added": self.files_added,
            "files_modified": [m.to_dict() for m in self.files_modified],
            "development_only_markers": self.development_only_markers,
            "capabilities": self.capabilities,
            "validation_status": self.validation_status,
            "reversal_metadata": self.reversal_metadata,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IntegrationManifest:
        mods = [ModifiedFileRecord.from_dict(m) for m in data.get("files_modified", [])]
        return cls(
            project=data["project"],
            framework=data["framework"],
            adapter=data["adapter"],
            harness_version=data.get("harness_version", CURRENT_HARNESS_VERSION),
            integration_mode=data.get("integration_mode", "DEV_OR_REVIEW"),
            created_at=data.get("created_at", time.time()),
            files_added=data.get("files_added", []),
            files_modified=mods,
            development_only_markers=data.get("development_only_markers", []),
            capabilities=data.get("capabilities", {}),
            validation_status=data.get("validation_status", "VALIDATED"),
            reversal_metadata=data.get("reversal_metadata", {}),
        )

    def save(self, project_dir: str | Path) -> Path:
        p = Path(project_dir) / MANIFEST_FILENAME
        p.write_text(self.to_json(), encoding="utf-8")
        return p

    @classmethod
    def load(cls, project_dir: str | Path) -> Optional[IntegrationManifest]:
        p = Path(project_dir) / MANIFEST_FILENAME
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None
