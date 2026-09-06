"""
Persistent Installation State Registry.

Manages persistent state in ~/.desktop_webview_reviewer/installation_state.json.
Guarantees atomic file writes and crash recovery.
Never stores credentials, tokens, or private keys.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from core.version import get_version_info
from runtime.lifecycle.models import InstallationStateRecord

logger = logging.getLogger("desktop_webview.lifecycle.registry")


def get_state_file_path() -> Path:
    """Returns the authoritative path to the local installation state JSON file."""
    custom_dir = os.environ.get("DESKTOP_REVIEWER_STATE_DIR")
    if custom_dir:
        base_dir = Path(custom_dir).resolve()
    else:
        base_dir = Path.home() / ".desktop_webview_reviewer"

    return base_dir / "installation_state.json"


class InstallationRegistry:
    """Read/write controller for persistent installation state."""

    def __init__(self, state_file: Optional[Path] = None):
        self.state_file = state_file or get_state_file_path()

    def get_state(self) -> InstallationStateRecord:
        """Loads persistent state, creating or repairing if missing or corrupted."""
        if not self.state_file.exists():
            return self._initialize_default_state()

        try:
            raw_text = self.state_file.read_text(encoding="utf-8")
            data = json.loads(raw_text)
            return InstallationStateRecord.from_dict(data)
        except Exception as exc:
            logger.warning(
                "Failed to parse installation state at %s: %s. Re-initializing default.",
                self.state_file,
                exc,
            )
            # Create a backup of corrupt state before initializing default
            try:
                backup = self.state_file.with_suffix(".corrupt.bak")
                shutil.copy2(self.state_file, backup)
            except Exception:
                pass
            return self._initialize_default_state()

    def save_state(self, record: InstallationStateRecord) -> None:
        """Atomically saves installation state to disk using a temporary file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        payload = json.dumps(record.to_dict(), indent=2)

        # Atomic write: write to temp file in same directory, then atomic rename
        temp_fd, temp_path_str = tempfile.mkstemp(
            prefix="inst_state_",
            suffix=".tmp",
            dir=str(self.state_file.parent),
        )
        temp_path = Path(temp_path_str)
        try:
            with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
                f.write(payload)
                f.flush()
                os.fsync(f.fileno())

            # Atomic replace
            os.replace(temp_path, self.state_file)
        except Exception:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except Exception:
                    pass
            raise

    def _initialize_default_state(self) -> InstallationStateRecord:
        """Creates and persists an initial state based on the active runtime environment."""
        vinfo = get_version_info()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        record = InstallationStateRecord(
            installed_version=vinfo.product_version,
            previous_known_good_version=None,
            pinned_version=None,
            channel="stable",
            installation_timestamp=now_iso,
            last_successful_validation=now_iso,
            runtime_location=vinfo.runtime_path,
            package_identity=vinfo.product_name,
        )
        self.save_state(record)
        return record

    def record_validation_success(self, version: Optional[str] = None) -> InstallationStateRecord:
        """Records a successful validation run."""
        state = self.get_state()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        if version:
            state.installed_version = version
        state.last_successful_validation = now_iso
        self.save_state(state)
        return state

    def set_pin(self, version: str) -> InstallationStateRecord:
        """Pins the product installation to an explicit version."""
        state = self.get_state()
        state.pinned_version = version.strip()
        self.save_state(state)
        return state

    def clear_pin(self) -> InstallationStateRecord:
        """Removes the active version pin."""
        state = self.get_state()
        state.pinned_version = None
        self.save_state(state)
        return state

    def record_update_success(
        self,
        new_version: str,
        previous_version: Optional[str] = None,
    ) -> InstallationStateRecord:
        """Commits a successful update transaction."""
        state = self.get_state()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state.previous_known_good_version = previous_version or state.installed_version
        state.installed_version = new_version
        state.last_successful_validation = now_iso
        state.last_update_status = "SUCCESS"
        state.last_update_attempt = now_iso
        self.save_state(state)
        return state

    def record_update_failure(self, attempted_version: str, reason: str) -> InstallationStateRecord:
        """Records an update failure for diagnostics."""
        state = self.get_state()
        now_iso = datetime.datetime.now(datetime.timezone.utc).isoformat()
        state.last_update_status = f"FAILED: {reason}"
        state.last_update_attempt = now_iso
        self.save_state(state)
        return state
