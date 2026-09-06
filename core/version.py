"""
Authoritative Version Contract for Desktop WebView Reviewer 2.0.

Provides a single programmatic source of truth for:
- Product name and product version
- Installed package version
- Git commit metadata
- Installation source
- Runtime and executable paths (Python, CLI, MCP)
- Skill installation path and metadata
"""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

PRODUCT_NAME: str = "Desktop WebView Reviewer"
PACKAGE_NAME: str = "desktop-webview-reviewer"
PRODUCT_VERSION: str = "2.0.0b1"  # Canonical codebase baseline version


@dataclass(frozen=True)
class VersionInfo:
    """Structured, authoritative version and environment contract."""

    product_name: str
    product_version: str
    package_version: str
    git_commit: Optional[str]
    installation_source: str
    runtime_path: str
    mcp_executable: Optional[str]
    skill_installation_path: Optional[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def summary(self) -> str:
        commit_str = f" ({self.git_commit[:7]})" if self.git_commit else ""
        return (
            f"{self.product_name} v{self.product_version}{commit_str} "
            f"[{self.installation_source}] via Python {sys.version.split()[0]}"
        )


def _resolve_git_commit(repo_root: Path) -> Optional[str]:
    """Resolves current git commit hash if available without exposing secrets."""
    # 1. Environment override if set in CI/CD
    env_commit = os.environ.get("DESKTOP_REVIEWER_GIT_COMMIT")
    if env_commit:
        return env_commit.strip()

    # 2. Check git rev-parse if .git directory exists
    git_dir = repo_root / ".git"
    if git_dir.exists():
        try:
            res = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=str(repo_root),
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                commit = res.stdout.strip()
                if commit and len(commit) >= 7:
                    return commit
        except Exception:
            pass

    return None


def _resolve_package_version() -> str:
    """Resolves installed package version from metadata or falls back to PRODUCT_VERSION."""
    try:
        return importlib.metadata.version(PACKAGE_NAME)
    except Exception:
        return PRODUCT_VERSION


def _resolve_installation_source(repo_root: Path) -> str:
    """Identifies installation source (e.g. editable, installed_wheel, source_checkout)."""
    try:
        dist = importlib.metadata.distribution(PACKAGE_NAME)
        direct_url_file = dist.read_text("direct_url.json")
        if direct_url_file:
            if '"editable": true' in direct_url_file or '"dir_info": {"editable": true}' in direct_url_file:
                return "editable"
            return "direct_wheel"
    except Exception:
        pass

    if (repo_root / "pyproject.toml").exists() and (repo_root / ".git").exists():
        return "source_checkout"

    return "installed_package"


def _resolve_mcp_executable() -> Optional[str]:
    """Finds the desktop-webview-mcp executable path if discoverable."""
    # Check PATH first
    mcp_path = shutil.which("desktop-webview-mcp")
    if mcp_path:
        return mcp_path

    # Check same directory as current Python executable (e.g. .venv/Scripts)
    py_dir = Path(sys.executable).parent
    for candidate in ("desktop-webview-mcp.exe", "desktop-webview-mcp"):
        p = py_dir / candidate
        if p.is_file():
            return str(p)

    return None


def _resolve_skill_path(repo_root: Path) -> Optional[str]:
    """Locates the installed or repository Antigravity skill directory."""
    # 1. Check user/global Antigravity config
    global_skill = Path.home() / ".gemini" / "config" / "skills" / "desktop-webview-reviewer"
    if global_skill.exists() and (global_skill / "SKILL.md").is_file():
        return str(global_skill.resolve())

    # 2. Check repository skill path
    repo_skill = repo_root / "skills" / "desktop-webview-reviewer"
    if repo_skill.exists() and (repo_skill / "SKILL.md").is_file():
        return str(repo_skill.resolve())

    return None


def get_version_info() -> VersionInfo:
    """Returns authoritative VersionInfo representing active product runtime."""
    repo_root = Path(__file__).resolve().parent.parent

    pkg_version = _resolve_package_version()
    # If package version is discoverable, runtime matches package; else canonical version
    prod_version = pkg_version if pkg_version else PRODUCT_VERSION

    return VersionInfo(
        product_name=PRODUCT_NAME,
        product_version=prod_version,
        package_version=pkg_version,
        git_commit=_resolve_git_commit(repo_root),
        installation_source=_resolve_installation_source(repo_root),
        runtime_path=str(Path(sys.executable).resolve()),
        mcp_executable=_resolve_mcp_executable(),
        skill_installation_path=_resolve_skill_path(repo_root),
    )


# Authoritative module-level export
__version__ = PRODUCT_VERSION
