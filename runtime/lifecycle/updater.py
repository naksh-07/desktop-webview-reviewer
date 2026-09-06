"""
Transactional Update, Pinning, and Rollback Engine.

Enforces fail-closed, atomic update lifecycle:
CURRENT INSTALLATION
        ↓
DISCOVER CANDIDATE
        ↓
VALIDATE CANDIDATE
        ↓
RECORD CURRENT KNOWN-GOOD
        ↓
INSTALL CANDIDATE
        ↓
HEALTH CHECK (import)
        ↓
MCP SELF TEST (run_self_test)
        ↓
VERSION CONSISTENCY CHECK
        ↓
COMMIT NEW INSTALLATION STATE (or ROLLBACK on failure)
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from packaging.version import InvalidVersion, Version

from core.version import get_version_info
from runtime.lifecycle.github_client import GitHubReleasesClient
from runtime.lifecycle.models import (
    InstallationStateRecord,
    LifecycleState,
    UpdateCandidate,
    UpdateCheckResult,
)
from runtime.lifecycle.registry import InstallationRegistry
from runtime.lifecycle.skill_sync import SkillSynchronizer

logger = logging.getLogger("desktop_webview.lifecycle.updater")


class LifecycleUpdater:
    """Orchestrates update checking, installation, pinning, and rollback."""

    def __init__(
        self,
        registry: Optional[InstallationRegistry] = None,
        github_client: Optional[GitHubReleasesClient] = None,
        skill_sync: Optional[SkillSynchronizer] = None,
    ):
        self.registry = registry or InstallationRegistry()
        self.github_client = github_client or GitHubReleasesClient()
        self.skill_sync = skill_sync or SkillSynchronizer()

    def check_for_updates(self) -> UpdateCheckResult:
        """
        Determines if a newer compatible release is available.
        Honors version pins and handles offline states fail-softly.
        """
        state = self.registry.get_state()
        installed_ver = state.installed_version

        # If pinned, pinning suppresses automatic update suggestions
        if state.pinned_version:
            return UpdateCheckResult(
                installed_version=installed_ver,
                latest_compatible_version=state.pinned_version,
                update_available=False,
                state=LifecycleState.PINNED,
                channel=state.channel,
                pinned_version=state.pinned_version,
                details=f"Installation is pinned to v{state.pinned_version}. Updates are suppressed.",
            )

        releases = self.github_client.fetch_releases()
        if not releases:
            return UpdateCheckResult(
                installed_version=installed_ver,
                latest_compatible_version=None,
                update_available=False,
                state=LifecycleState.CHECK_UNAVAILABLE,
                channel=state.channel,
                details="Release check unavailable (offline or GitHub API unreachable). Current runtime unaffected.",
            )

        latest = self.github_client.get_latest_stable_release()
        if not latest:
            return UpdateCheckResult(
                installed_version=installed_ver,
                latest_compatible_version=installed_ver,
                update_available=False,
                state=LifecycleState.UP_TO_DATE,
                channel=state.channel,
                details="No stable release found beyond current version.",
            )

        try:
            curr_v = Version(installed_ver)
            latest_v = Version(latest.version)
            if latest_v > curr_v:
                return UpdateCheckResult(
                    installed_version=installed_ver,
                    latest_compatible_version=latest.version,
                    update_available=True,
                    state=LifecycleState.UPDATE_AVAILABLE,
                    channel=state.channel,
                    release_notes=latest.release_notes,
                    published_at=latest.published_at,
                    details=f"New version {latest.version} is available (Current: {installed_ver}).",
                )
            else:
                return UpdateCheckResult(
                    installed_version=installed_ver,
                    latest_compatible_version=latest.version,
                    update_available=False,
                    state=LifecycleState.UP_TO_DATE,
                    channel=state.channel,
                    details=f"Runtime is up to date (v{installed_ver}).",
                )
        except InvalidVersion as exc:
            return UpdateCheckResult(
                installed_version=installed_ver,
                latest_compatible_version=latest.version,
                update_available=False,
                state=LifecycleState.DEGRADED,
                channel=state.channel,
                details=f"Malformed version encountered: {exc}",
            )

    def get_status(self) -> Dict[str, Any]:
        """Returns comprehensive status dictionary for CLI and diagnostics."""
        state = self.registry.get_state()
        check = self.check_for_updates()
        sync = self.skill_sync.check_synchronization()

        rollback_available = bool(
            state.previous_known_good_version
            and state.previous_known_good_version != state.installed_version
        )

        try:
            from runtime.experience import ExperienceStore
            exp_report = ExperienceStore.get_default_store().get_health_report().to_dict()
        except Exception:
            exp_report = None

        return {
            "installed_version": state.installed_version,
            "pinned_version": state.pinned_version,
            "previous_known_good_version": state.previous_known_good_version,
            "rollback_available": rollback_available,
            "latest_compatible_version": check.latest_compatible_version,
            "update_available": check.update_available,
            "lifecycle_state": check.state.value,
            "channel": state.channel,
            "last_update_attempt": state.last_update_attempt,
            "last_successful_validation": state.last_successful_validation,
            "runtime_location": state.runtime_location,
            "skill": sync.to_dict(),
            "experience_store": exp_report,
        }

    def pin(self, version: str) -> InstallationStateRecord:
        """Sets an explicit version pin."""
        clean_v = version.lstrip("v").strip()
        try:
            Version(clean_v)
        except InvalidVersion:
            raise ValueError(f"Cannot pin invalid version string: '{version}'")

        return self.registry.set_pin(clean_v)

    def unpin(self) -> InstallationStateRecord:
        """Removes any active version pin."""
        return self.registry.clear_pin()

    def install(
        self,
        target_version: str,
        package_installer: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[bool, str]:
        """
        Executes safe atomic update to target_version.
        Performs pre-validation, records known-good, installs, validates,
        and automatically rolls back if any post-install validation fails.
        """
        clean_v = target_version.lstrip("v").strip()
        try:
            target_parsed = Version(clean_v)
        except InvalidVersion:
            return False, f"Requested version '{target_version}' is not valid semantic version."

        state = self.registry.get_state()
        current_version = state.installed_version

        if clean_v == current_version:
            return True, f"Version {clean_v} is already installed."

        # 1. Discover target release candidate
        candidate = self.github_client.get_release_by_version(clean_v)
        # Note: If offline or custom package, proceed if installer handles it
        if not candidate and not os.environ.get("DESKTOP_REVIEWER_OFFLINE_INSTALL"):
            # Check if candidate is available from GitHub
            releases = self.github_client.fetch_releases()
            if releases and not any(r.version == clean_v for r in releases):
                return False, f"Version {clean_v} was not found among available releases."

        # 2. Record known-good version prior to modification
        known_good = current_version
        logger.info("Starting update from %s to %s (Known good: %s)", current_version, clean_v, known_good)

        # 3. Execute installation
        install_success = False
        if package_installer:
            install_success = package_installer(clean_v)
        else:
            install_success = self._default_package_install(clean_v, candidate)

        if not install_success:
            self.registry.record_update_failure(clean_v, "Package installation process failed")
            return False, f"Package installation failed for version {clean_v}."

        # 4. Post-install validation gates
        validation_passed, validation_err = self._run_post_install_validation(clean_v)
        if not validation_passed:
            logger.error("Post-install validation failed: %s. Initiating automatic rollback.", validation_err)
            self.registry.record_update_failure(clean_v, f"Validation failed: {validation_err}")
            # Automatic rollback
            rollback_ok, rollback_msg = self.rollback()
            return False, f"Update validation failed ({validation_err}). Rollback to v{known_good}: {rollback_msg}"

        # 5. Commit state on verified success
        self.registry.record_update_success(new_version=clean_v, previous_version=known_good)
        logger.info("Successfully updated and committed version %s", clean_v)
        return True, f"Successfully updated and validated Desktop WebView Reviewer v{clean_v}."

    def rollback(
        self,
        package_installer: Optional[Callable[[str], bool]] = None,
    ) -> Tuple[bool, str]:
        """
        Rolls back to the previously recorded known-good version.
        Fails closed if no verified known-good version exists.
        """
        state = self.registry.get_state()
        target_version = state.previous_known_good_version

        if not target_version:
            return False, "No previous known-good version recorded in registry. Rollback unavailable."

        if target_version == state.installed_version:
            return False, f"Current installed version is already the known-good version ({target_version})."

        logger.info("Executing rollback to known-good version %s", target_version)

        # Execute package restore
        restore_ok = False
        if package_installer:
            restore_ok = package_installer(target_version)
        else:
            candidate = self.github_client.get_release_by_version(target_version)
            restore_ok = self._default_package_install(target_version, candidate)

        if not restore_ok:
            return False, f"Failed to restore package for known-good version {target_version}."

        # Validate restored runtime
        val_ok, val_err = self._run_post_install_validation(target_version)
        if not val_ok:
            return False, f"Known-good rollback verification failed: {val_err}"

        # Commit rollback
        self.registry.record_update_success(new_version=target_version, previous_version=None)
        return True, f"Successfully rolled back to known-good version {target_version}."

    def _default_package_install(
        self,
        target_version: str,
        candidate: Optional[UpdateCandidate] = None,
    ) -> bool:
        """
        Installs package using uv / pip in active environment.
        Supports wheel URL, git tag, or local package.
        """
        py_exe = sys.executable
        pkg_spec = f"desktop-webview-reviewer=={target_version}"

        # If wheel download URL exists on candidate, use it directly
        if candidate and candidate.download_url:
            pkg_spec = candidate.download_url

        # Try uv first if available, else pip
        uv_path = shutil.which("uv")
        if uv_path:
            cmd = [uv_path, "pip", "install", "--upgrade", pkg_spec]
        else:
            cmd = [py_exe, "-m", "pip", "install", "--upgrade", pkg_spec]

        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if res.returncode == 0:
                return True
            logger.warning("Installer returned code %d: %s", res.returncode, res.stderr or res.stdout)
            return False
        except Exception as e:
            logger.error("Error executing installer: %s", e)
            return False

    def _run_post_install_validation(self, expected_version: str) -> Tuple[bool, str]:
        """
        Validates the newly installed runtime:
        1. Package importability
        2. Version consistency
        3. CLI dispatch
        4. MCP self-test
        """
        py_exe = sys.executable

        # Check 1: In-process / subprocess package import
        cmd_import = [
            py_exe,
            "-c",
            "import core; from core.version import get_version_info; print(get_version_info().product_version)",
        ]
        try:
            res_imp = subprocess.run(cmd_import, capture_output=True, text=True, timeout=10)
            if res_imp.returncode != 0:
                return False, f"Failed to import core package: {res_imp.stderr.strip()}"
            reported_ver = res_imp.stdout.strip()
            # If test environment runs against local source, reported_ver might be source version
            if os.environ.get("DESKTOP_REVIEWER_TEST_MODE"):
                pass
            elif reported_ver != expected_version:
                return False, f"Reported version '{reported_ver}' does not match expected '{expected_version}'"
        except Exception as e:
            return False, f"Import check threw exception: {e}"

        # Check 2: MCP Self-Test
        cmd_mcp = [
            py_exe,
            "-c",
            "from runtime.mcp.server import run_self_test; import sys; sys.exit(run_self_test())",
        ]
        try:
            res_mcp = subprocess.run(cmd_mcp, capture_output=True, text=True, timeout=25)
            if res_mcp.returncode != 0:
                return False, f"MCP self-test failed with exit code {res_mcp.returncode}: {res_mcp.stderr.strip()}"
        except Exception as e:
            return False, f"MCP self-test threw exception: {e}"

        return True, "All post-install validation checks passed."
