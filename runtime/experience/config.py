"""
Configuration and Directory Resolution for Desktop WebView Reviewer Experience Store.

Resolves durable storage paths with strict precedence:
1. Explicit path passed to ExperienceConfig
2. Environment override (DESKTOP_REVIEWER_EXPERIENCE_DIR)
3. Platform default (%LOCALAPPDATA%\\DesktopWebViewReviewer\\experience on Windows)

Guarantees the Experience Data Directory is outside the source repository.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional, Union

logger = logging.getLogger("desktop_webview.experience.config")

DEFAULT_SUBDIR_NAME = "DesktopWebViewReviewer"
EXPERIENCE_SUBDIR_NAME = "experience"
ENV_EXPERIENCE_DIR = "DESKTOP_REVIEWER_EXPERIENCE_DIR"


def get_default_experience_dir() -> Path:
    """
    Resolves the canonical platform default Experience Data Directory.
    
    Default on Windows:
        %LOCALAPPDATA%\\DesktopWebViewReviewer\\experience
    Default on POSIX / fallback:
        ~/.local/share/DesktopWebViewReviewer/experience
    """
    if sys.platform == "win32" or platform.system().lower() == "windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            base = Path(local_app_data)
        else:
            base = Path.home() / "AppData" / "Local"
    else:
        # Linux / macOS / BSD
        xdg_data = os.environ.get("XDG_DATA_HOME")
        if xdg_data:
            base = Path(xdg_data)
        else:
            base = Path.home() / ".local" / "share"

    return (base / DEFAULT_SUBDIR_NAME / EXPERIENCE_SUBDIR_NAME).resolve()


def resolve_experience_dir(custom_path: Optional[Union[str, Path]] = None) -> Path:
    """
    Resolves the authoritative Experience Data Directory following precedence:
    1. custom_path if provided
    2. DESKTOP_REVIEWER_EXPERIENCE_DIR environment variable
    3. platform default (%LOCALAPPDATA%\\DesktopWebViewReviewer\\experience)
    """
    # 1. Explicit argument
    if custom_path is not None:
        p = Path(custom_path).expanduser().resolve()
        return p

    # 2. Environment override
    env_dir = os.environ.get(ENV_EXPERIENCE_DIR)
    if env_dir and env_dir.strip():
        p = Path(env_dir.strip()).expanduser().resolve()
        return p

    # 3. Platform default
    return get_default_experience_dir()


@dataclass
class ExperienceConfig:
    """
    Structured configuration for the Experience Store subsystem.
    """
    base_dir: Optional[Path] = None
    database_name: str = "experience.db"
    enable_wal_mode: bool = True
    busy_timeout_ms: int = 5000
    fail_safe_mode: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        self.base_dir = resolve_experience_dir(self.base_dir)

    @property
    def database_path(self) -> Path:
        """Returns full absolute path to the SQLite database file."""
        assert self.base_dir is not None
        return self.base_dir / self.database_name

    @property
    def installation_id_path(self) -> Path:
        """Returns full path to the persistent installation ID JSON file."""
        assert self.base_dir is not None
        return self.base_dir / "installation_id.json"

    def ensure_directories(self) -> Path:
        """Creates experience data directory tree if not already existing."""
        assert self.base_dir is not None
        self.base_dir.mkdir(parents=True, exist_ok=True)
        return self.base_dir

    def get_or_create_installation_id(self) -> str:
        """
        Retrieves durable installation UUID from installation_id.json or generates
        and commits a new one if not present.
        """
        self.ensure_directories()
        id_path = self.installation_id_path
        if id_path.exists():
            try:
                data = json.loads(id_path.read_text(encoding="utf-8"))
                stored_id = data.get("installation_id")
                if stored_id and isinstance(stored_id, str):
                    return stored_id.strip()
            except Exception as e:
                logger.warning("Could not parse existing installation_id.json at %s: %s", id_path, e)

        # Generate fresh UUID4 installation ID
        new_id = f"inst_{uuid.uuid4().hex}"
        try:
            payload = {
                "installation_id": new_id,
                "platform": platform.system(),
                "created_via": "desktop_webview_reviewer.experience",
            }
            id_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning("Could not persist installation_id.json at %s: %s", id_path, e)

        return new_id

    def to_dict(self) -> Dict[str, Any]:
        """Returns inspectable configuration dictionary."""
        assert self.base_dir is not None
        return {
            "base_dir": str(self.base_dir),
            "database_path": str(self.database_path),
            "database_name": self.database_name,
            "enable_wal_mode": self.enable_wal_mode,
            "busy_timeout_ms": self.busy_timeout_ms,
            "fail_safe_mode": self.fail_safe_mode,
            "is_default_location": str(self.base_dir) == str(get_default_experience_dir()),
        }
