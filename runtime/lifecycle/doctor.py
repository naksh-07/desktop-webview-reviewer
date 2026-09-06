"""
Installation and Lifecycle Doctor.

Performs deep consistency checks across:
1. Package import and metadata alignment
2. CLI executable resolution and path integrity
3. MCP executable resolution and self-test
4. Skill path discovery and version metadata compatibility
5. Stale conflicting installation detection
6. State file integrity
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional
from packaging.version import InvalidVersion, Version

from core.version import get_version_info
from runtime.lifecycle.models import DoctorCheckResult, DoctorReport
from runtime.lifecycle.registry import InstallationRegistry
from runtime.lifecycle.skill_sync import SkillSynchronizer

logger = logging.getLogger("desktop_webview.lifecycle.doctor")


class LifecycleDoctor:
    """Runs installation health and consistency checks."""

    def __init__(
        self,
        registry: Optional[InstallationRegistry] = None,
        skill_sync: Optional[SkillSynchronizer] = None,
    ):
        self.registry = registry or InstallationRegistry()
        self.skill_sync = skill_sync or SkillSynchronizer()

    def run_doctor(self) -> DoctorReport:
        """Executes full suite of installation consistency checks."""
        vinfo = get_version_info()
        checks = []
        overall_passed = True

        # Check 1: Package import & core version resolution
        try:
            import core
            ver = getattr(core, "__version__", None)
            if ver == vinfo.product_version:
                checks.append(
                    DoctorCheckResult(
                        name="package_import",
                        status="PASS",
                        message=f"Core package imports cleanly and reports v{ver}.",
                        details={"version": ver},
                    )
                )
            else:
                checks.append(
                    DoctorCheckResult(
                        name="package_import",
                        status="WARN",
                        message=f"Core package version ({ver}) diverged from version info ({vinfo.product_version}).",
                        details={"core_version": ver, "vinfo_version": vinfo.product_version},
                    )
                )
        except Exception as e:
            overall_passed = False
            checks.append(
                DoctorCheckResult(
                    name="package_import",
                    status="FAIL",
                    message=f"Failed to import core package: {e}",
                )
            )

        # Check 2: Version consistency between state file and runtime
        state = self.registry.get_state()
        if state.installed_version == vinfo.product_version:
            checks.append(
                DoctorCheckResult(
                    name="state_consistency",
                    status="PASS",
                    message=f"Installation registry aligns with runtime (v{vinfo.product_version}).",
                    details={"state_version": state.installed_version},
                )
            )
        else:
            checks.append(
                DoctorCheckResult(
                    name="state_consistency",
                    status="WARN",
                    message=(
                        f"State file declares v{state.installed_version} while active runtime is "
                        f"v{vinfo.product_version}. Automatically reconciling state."
                    ),
                    details={"state_version": state.installed_version, "runtime_version": vinfo.product_version},
                )
            )
            # Self-heal state
            self.registry.record_validation_success(vinfo.product_version)

        # Check 3: CLI executable resolution
        cli_path = shutil.which("desktop-reviewer")
        if not cli_path:
            # Check current Python venv Scripts
            candidate = Path(sys.executable).parent / "desktop-reviewer.exe"
            if candidate.is_file():
                cli_path = str(candidate)

        if cli_path:
            checks.append(
                DoctorCheckResult(
                    name="cli_executable",
                    status="PASS",
                    message=f"CLI executable resolved at {cli_path}.",
                    details={"path": cli_path},
                )
            )
        else:
            checks.append(
                DoctorCheckResult(
                    name="cli_executable",
                    status="WARN",
                    message="desktop-reviewer executable not found on PATH or in current venv Scripts.",
                )
            )

        # Check 4: MCP executable resolution
        mcp_path = vinfo.mcp_executable or shutil.which("desktop-webview-mcp")
        if not mcp_path:
            candidate_mcp = Path(sys.executable).parent / "desktop-webview-mcp.exe"
            if candidate_mcp.is_file():
                mcp_path = str(candidate_mcp)

        if mcp_path:
            checks.append(
                DoctorCheckResult(
                    name="mcp_executable",
                    status="PASS",
                    message=f"MCP executable resolved at {mcp_path}.",
                    details={"path": mcp_path},
                )
            )
        else:
            checks.append(
                DoctorCheckResult(
                    name="mcp_executable",
                    status="WARN",
                    message="desktop-webview-mcp executable not found on system PATH.",
                )
            )

        # Check 5: MCP Self-Test execution
        try:
            from runtime.mcp.server import run_self_test
            mcp_code = run_self_test()
            if mcp_code == 0:
                checks.append(
                    DoctorCheckResult(
                        name="mcp_self_test",
                        status="PASS",
                        message="MCP server in-process self-test passed (7/7 checks).",
                    )
                )
            else:
                overall_passed = False
                checks.append(
                    DoctorCheckResult(
                        name="mcp_self_test",
                        status="FAIL",
                        message=f"MCP self-test failed with exit code {mcp_code}.",
                    )
                )
        except Exception as e:
            overall_passed = False
            checks.append(
                DoctorCheckResult(
                    name="mcp_self_test",
                    status="FAIL",
                    message=f"MCP self-test threw exception: {e}",
                )
            )

        # Check 6: Skill path discovery and synchronization
        sync_res = self.skill_sync.check_synchronization()
        if sync_res.is_compatible:
            checks.append(
                DoctorCheckResult(
                    name="skill_synchronization",
                    status="PASS",
                    message=(
                        f"Skill ({sync_res.skill_path}) v{sync_res.skill_version} is compatible "
                        f"with runtime v{vinfo.product_version}."
                    ),
                    details=sync_res.to_dict(),
                )
            )
        else:
            checks.append(
                DoctorCheckResult(
                    name="skill_synchronization",
                    status="WARN" if sync_res.skill_path else "INFO",
                    message=sync_res.diagnosis,
                    details=sync_res.to_dict(),
                )
            )

        # Check 7: Conflicting stale installations
        stale_detected = self._detect_stale_installations()
        if not stale_detected:
            checks.append(
                DoctorCheckResult(
                    name="stale_installation_detection",
                    status="PASS",
                    message="No conflicting stale desktop-webview-reviewer installations detected.",
                )
            )
        else:
            checks.append(
                DoctorCheckResult(
                    name="stale_installation_detection",
                    status="WARN",
                    message=f"Detected multiple/stale installations: {stale_detected}",
                    details={"stale_paths": stale_detected},
                )
            )

        # Check 8: Experience Store health and storage integrity
        try:
            from runtime.experience import ExperienceStore
            exp_store = ExperienceStore.get_default_store()
            health = exp_store.get_health_report()
            if health.health == "OK" and health.integrity_check == "ok":
                checks.append(
                    DoctorCheckResult(
                        name="experience_store",
                        status="PASS",
                        message=(
                            f"Experience Store operational at {health.storage_path} "
                            f"(schema v{health.schema_version}, {sum(health.record_counts.values())} records)."
                        ),
                        details=health.to_dict(),
                    )
                )
            else:
                checks.append(
                    DoctorCheckResult(
                        name="experience_store",
                        status="WARN",
                        message=(
                            f"Experience Store reported {health.health} status: {health.integrity_check} "
                            f"at {health.storage_path}."
                        ),
                        details=health.to_dict(),
                    )
                )
        except Exception as e:
            checks.append(
                DoctorCheckResult(
                    name="experience_store",
                    status="WARN",
                    message=f"Experience Store initialization check failed: {e}",
                )
            )

        # Check 9: Antigravity Correlation Bridge status (Milestone 2.1 Prompt 3)
        try:
            from runtime.experience.antigravity import AntigravityCorrelationBridge
            bridge = AntigravityCorrelationBridge.get_default_bridge()
            bstatus = bridge.get_status()
            bridge_details = bstatus.to_dict()

            if bstatus.enabled:
                checks.append(
                    DoctorCheckResult(
                        name="antigravity_bridge",
                        status="PASS",
                        message=(
                            f"Antigravity correlation bridge enabled "
                            f"(events accepted: {bstatus.events_accepted}, correlations: {bstatus.correlation_records}, "
                            f"privacy blocks: {bstatus.privacy_violations_blocked})."
                        ),
                        details=bridge_details,
                    )
                )
            else:
                checks.append(
                    DoctorCheckResult(
                        name="antigravity_bridge",
                        status="INFO",
                        message="Antigravity correlation bridge is installed but disabled via configuration.",
                        details=bridge_details,
                    )
                )
        except Exception as e:
            checks.append(
                DoctorCheckResult(
                    name="antigravity_bridge",
                    status="INFO",
                    message=f"Antigravity correlation bridge not configured or unavailable: {e}",
                )
            )

        # Check 10: Learning, Governance & Field Intelligence (Milestone 2.1 Prompt 4)
        try:
            from runtime.experience import ExperienceStore
            from runtime.experience.learning import LearningSafetyGate, KnowledgeDecayEngine
            store = ExperienceStore.get_default_store()
            counts = store.get_record_counts()
            candidates = store.get_improvement_candidates(limit=100)
            pending_gov = [c for c in candidates if c.status.value in ("VALIDATION_REQUIRED", "CANDIDATE")]
            durable_items = store.get_durable_knowledge(limit=100)
            decay_engine = KnowledgeDecayEngine(store)
            decay_eval = decay_engine.evaluate_staleness()

            learning_details = {
                "observations": counts.get("observations", 0),
                "patterns": counts.get("detected_patterns", 0),
                "improvement_candidates": counts.get("improvement_candidates", 0),
                "governance_pending": len(pending_gov),
                "durable_knowledge": len(durable_items),
                "review_due": len(decay_eval.get("review_due", [])),
                "stale_knowledge": len(decay_eval.get("stale", [])),
                "privacy_violations_blocked": LearningSafetyGate.blocked_violations_count,
            }
            checks.append(
                DoctorCheckResult(
                    name="learning_and_governance",
                    status="PASS",
                    message=(
                        f"Learning & Governance engine operational (obs: {learning_details['observations']}, "
                        f"patterns: {learning_details['patterns']}, candidates: {learning_details['improvement_candidates']}, "
                        f"pending review: {learning_details['governance_pending']}, durable: {learning_details['durable_knowledge']})."
                    ),
                    details=learning_details,
                )
            )
        except Exception as e:
            checks.append(
                DoctorCheckResult(
                    name="learning_and_governance",
                    status="INFO",
                    message=f"Learning & Governance status unavailable: {e}",
                )
            )

        return DoctorReport(
            passed=overall_passed,
            installed_version=vinfo.product_version,
            runtime_location=vinfo.runtime_path,
            checks=checks,
        )

    def _detect_stale_installations(self) -> list[str]:
        """Detects whether multiple competing versions exist in sys.path or user site-packages."""
        stale = []
        visited = set()
        for p in sys.path:
            p_obj = Path(p).resolve()
            if not p_obj.exists() or p_obj in visited:
                continue
            visited.add(p_obj)

            # Look for egg-info or dist-info of desktop-webview-reviewer
            for dist_info in p_obj.glob("desktop_webview_reviewer-*.dist-info"):
                stale.append(str(dist_info))

        # If current source repo is visited along with a different dist-info, note it
        if len(stale) > 1:
            return stale
        return []
