"""
Surgical Harness Injector & Reversal Subsystem (Architecture H).
Implements `harness init`, dry-run preview, and reversible `harness remove`
without overwriting entire files or destroying developer modifications.
"""

from __future__ import annotations
import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple

from runtime.harness.detector import ProjectDetector, DetectionResult
from runtime.harness.adapters import get_adapter_for_framework
from runtime.harness.adapters.base import BaseHarnessAdapter
from runtime.harness.manifest import (
    IntegrationManifest,
    ModifiedFileRecord,
    MANIFEST_FILENAME,
    CURRENT_HARNESS_VERSION,
)


class HarnessInjectionError(Exception):
    """Raised on injection failure, invalid project, or ambiguous framework."""
    pass


class UnsafeReversalError(Exception):
    """Raised when harness removal detects corrupt, missing, or altered markers."""
    pass


@dataclass
class InjectionPlan:
    """Preview of planned surgical integration changes."""
    project_path: str
    framework: str
    adapter_name: str
    files_to_add: List[Tuple[str, str]] = field(default_factory=list)  # (rel_path, content)
    files_to_modify: List[Tuple[str, str, str, str]] = field(default_factory=list)  # (rel_path, target_file, snippet, original_content)
    markers: Tuple[str, str] = ("", "")
    capabilities: Dict[str, str] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_path": self.project_path,
            "framework": self.framework,
            "adapter_name": self.adapter_name,
            "files_to_add": [f[0] for f in self.files_to_add],
            "files_to_modify": [f[0] for f in self.files_to_modify],
            "markers": list(self.markers),
            "capabilities": self.capabilities,
            "warnings": self.warnings,
        }


class HarnessInjector:
    """
    Surgically introduces and safely removes Reviewer Test Harness integrations.
    """

    @classmethod
    def plan(cls, project_dir: str | Path, framework_override: Optional[str] = None) -> InjectionPlan:
        root = Path(project_dir).resolve()
        if not root.exists():
            raise HarnessInjectionError(f"Directory not found: {project_dir}")

        detection = ProjectDetector.detect(root)
        fw = framework_override or detection.framework
        if not fw:
            reasons = "; ".join(detection.reasons)
            raise HarnessInjectionError(f"Could not determine framework for project: {reasons}")

        adapter = get_adapter_for_framework(fw)
        if not adapter:
            raise HarnessInjectionError(f"No adapter registered for framework: '{fw}'")

        # 1. Determine client file to add
        client_rel, client_content = adapter.generate_harness_client_file(str(root), {
            "app_id": root.name,
            "session_id": "dev_session",
        })

        # 2. Determine target entry point
        entry_points = detection.entry_points
        if not entry_points:
            # Fallback default entry points
            if fw == "electron":
                entry_points = ["main.js", "index.js"]
            elif fw == "webview2":
                entry_points = ["MainWindow.xaml.cs", "Program.cs"]
            elif fw in ("qt", "qtwebengine"):
                entry_points = ["main.py", "app.py"]

        target_rel = None
        for ep in entry_points:
            if (root / ep).exists():
                target_rel = ep
                break

        files_to_modify: List[Tuple[str, str, str, str]] = []
        warnings: List[str] = []

        if target_rel:
            target_path = root / target_rel
            orig_content = target_path.read_text(encoding="utf-8", errors="ignore")
            snippet = adapter.get_injection_snippet(client_rel)
            files_to_modify.append((target_rel, str(target_path), snippet, orig_content))
        else:
            warnings.append(f"No active entry point found from candidates: {entry_points}. Manual initialization required.")

        caps = {k: v.value for k, v in adapter.get_supported_capabilities().items()}

        return InjectionPlan(
            project_path=str(root),
            framework=fw,
            adapter_name=adapter.adapter_name,
            files_to_add=[(client_rel, client_content)],
            files_to_modify=files_to_modify,
            markers=adapter.get_dev_marker_pair(),
            capabilities=caps,
            warnings=warnings,
        )

    @classmethod
    def apply(cls, plan: InjectionPlan, dry_run: bool = False) -> Tuple[IntegrationManifest, Dict[str, Any]]:
        """
        Applies the injection plan surgically or previews via dry-run.
        Never overwrites entire files.
        """
        root = Path(plan.project_path)
        report: Dict[str, Any] = {
            "dry_run": dry_run,
            "framework": plan.framework,
            "adapter": plan.adapter_name,
            "files_added": [],
            "files_modified": [],
            "warnings": list(plan.warnings),
            "status": "READY" if not dry_run else "PREVIEW",
        }

        if dry_run:
            report["files_added"] = [f[0] for f in plan.files_to_add]
            report["files_modified"] = [f[0] for f in plan.files_to_modify]
            manifest_preview = IntegrationManifest(
                project=root.name,
                framework=plan.framework,
                adapter=plan.adapter_name,
                files_added=report["files_added"],
                capabilities=plan.capabilities,
                validation_status="DRY_RUN",
            )
            return manifest_preview, report

        # Live execution:
        # Check if already integrated
        existing_manifest = IntegrationManifest.load(root)
        if existing_manifest:
            report["warnings"].append("Project already contains an existing Reviewer Harness manifest. Overwriting.")

        # 1. Write added files
        added_paths: List[str] = []
        for rel_path, content in plan.files_to_add:
            full_path = root / rel_path
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding="utf-8")
            added_paths.append(rel_path)
            report["files_added"].append(rel_path)

        # 2. Surgically modify target files
        modified_records: List[ModifiedFileRecord] = []
        begin_marker, end_marker = plan.markers

        for rel_path, full_path_str, snippet, orig_content in plan.files_to_modify:
            target_path = Path(full_path_str)
            orig_hash = hashlib.sha256(orig_content.encode("utf-8")).hexdigest()

            # Guard: check if marker already exists
            if begin_marker in orig_content and end_marker in orig_content:
                report["warnings"].append(f"Markers already present in {rel_path}. Updating snippet in-place.")
                # Replace existing block
                pattern = re.compile(re.escape(begin_marker) + r".*?" + re.escape(end_marker), re.DOTALL)
                new_content = pattern.sub(snippet.strip(), orig_content)
            else:
                # Prepend or append cleanly
                # For JS/TS/Py, prepend after initial comments or top
                new_content = f"{snippet.strip()}\n\n{orig_content}"

            target_path.write_text(new_content, encoding="utf-8")
            mod_hash = hashlib.sha256(new_content.encode("utf-8")).hexdigest()

            rec = ModifiedFileRecord(
                path=rel_path,
                original_sha256=orig_hash,
                modified_sha256=mod_hash,
                markers=[begin_marker, end_marker],
                injected_snippet=snippet,
            )
            modified_records.append(rec)
            report["files_modified"].append(rel_path)

        # 3. Write integration manifest
        manifest = IntegrationManifest(
            project=root.name,
            framework=plan.framework,
            adapter=plan.adapter_name,
            harness_version=CURRENT_HARNESS_VERSION,
            integration_mode="DEV_OR_REVIEW",
            files_added=added_paths,
            files_modified=modified_records,
            development_only_markers=[begin_marker, end_marker],
            capabilities=plan.capabilities,
            validation_status="VALIDATED",
            reversal_metadata={
                "injection_timestamp": report.get("timestamp"),
                "clean_reversal_supported": True,
            },
        )
        manifest.save(root)
        report["manifest_file"] = MANIFEST_FILENAME
        return manifest, report

    @classmethod
    def remove(cls, project_dir: str | Path) -> Dict[str, Any]:
        """
        Reverses Reviewer Harness integration using manifest audit trail.
        Surgically extracts injected markers and restores developer files.
        """
        root = Path(project_dir).resolve()
        manifest = IntegrationManifest.load(root)
        if not manifest:
            raise HarnessInjectionError(f"No {MANIFEST_FILENAME} manifest found in {project_dir}. Cannot safely reverse.")

        report: Dict[str, Any] = {
            "project": manifest.project,
            "framework": manifest.framework,
            "files_removed": [],
            "files_restored": [],
            "warnings": [],
            "status": "REMOVED",
        }

        # 1. Delete added files
        for rel_path in manifest.files_added:
            target = root / rel_path
            if target.exists():
                try:
                    target.unlink()
                    report["files_removed"].append(rel_path)
                except Exception as e:
                    report["warnings"].append(f"Failed to delete {rel_path}: {e}")

        # 2. Surgically strip injected markers from modified files
        for mod in manifest.files_modified:
            target = root / mod.path
            if not target.exists():
                report["warnings"].append(f"Modified file {mod.path} was deleted externally.")
                continue

            content = target.read_text(encoding="utf-8", errors="ignore")
            markers = mod.markers
            if len(markers) >= 2:
                begin_m, end_m = markers[0], markers[1]
                if begin_m in content and end_m in content:
                    pattern = re.compile(r"\s*" + re.escape(begin_m) + r".*?" + re.escape(end_m) + r"\s*", re.DOTALL)
                    cleaned = pattern.sub("\n", content)
                    target.write_text(cleaned.strip() + "\n", encoding="utf-8")
                    report["files_restored"].append(mod.path)
                else:
                    raise UnsafeReversalError(
                        f"Unsafe removal aborted: markers in {mod.path} were altered or missing. "
                        f"Manual inspection required to prevent accidental code loss."
                    )
            else:
                report["warnings"].append(f"Incomplete marker metadata for {mod.path}.")

        # 3. Remove manifest itself
        manifest_path = root / MANIFEST_FILENAME
        if manifest_path.exists():
            manifest_path.unlink()

        return report
