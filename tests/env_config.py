"""
Shared test configuration and dynamic path resolver for desktop-webview-reviewer test suite.
"""

import os
import sys
from pathlib import Path


def get_skill_dir() -> Path:
    """Returns the resolved Path to the desktop-webview-reviewer skill directory."""
    if "DESKTOP_WEBVIEW_REVIEWER_DIR" in os.environ:
        return Path(os.environ["DESKTOP_WEBVIEW_REVIEWER_DIR"]).resolve()

    # Direct parent repository check (when tests/ is inside the repo root)
    repo_root = Path(__file__).resolve().parent.parent
    if (repo_root / "core").exists():
        return repo_root.resolve()

    home_skill = Path.home() / ".gemini" / "config" / "skills" / "desktop-webview-reviewer"
    if home_skill.exists():
        return home_skill.resolve()

    return repo_root.resolve()



def get_qt_skill_dir() -> Path:
    """Returns the resolved Path to the qt-desktop-reviewer skill directory."""
    if "QT_DESKTOP_REVIEWER_DIR" in os.environ:
        return Path(os.environ["QT_DESKTOP_REVIEWER_DIR"]).resolve()

    home_skill = Path.home() / ".gemini" / "config" / "skills" / "qt-desktop-reviewer"
    if home_skill.exists():
        return home_skill.resolve()

    return home_skill.resolve()


def get_python_exe() -> str:
    """Returns the current running Python executable path."""
    return sys.executable


# Ensure desktop-webview-reviewer is in sys.path
CORE_SKILL_DIR = str(get_skill_dir())
if CORE_SKILL_DIR not in sys.path:
    sys.path.insert(0, CORE_SKILL_DIR)
