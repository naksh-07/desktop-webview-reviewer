"""
Antigravity Skill Synchronization and Compatibility Analyzer.

Evaluates version alignment between:
1. Active Python runtime
2. Installed Antigravity skill package (SKILL.md frontmatter)
3. Repository skill definition
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Optional, Tuple
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from core.version import get_version_info
from runtime.lifecycle.models import SkillSyncStatus

logger = logging.getLogger("desktop_webview.lifecycle.skill_sync")


def _parse_skill_frontmatter(skill_md_path: Path) -> Tuple[Optional[str], Optional[str]]:
    """
    Extracts 'version' and 'compatible_runtime_range' from YAML frontmatter of SKILL.md.
    Does not require PyYAML dependency by using robust regex matching on header block.
    """
    if not skill_md_path.is_file():
        return None, None

    try:
        content = skill_md_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning("Could not read %s: %s", skill_md_path, e)
        return None, None

    # Frontmatter is delimited by --- at start of file
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return None, None

    frontmatter = match.group(1)
    version = None
    compat_range = None

    for line in frontmatter.splitlines():
        line = line.strip()
        if line.startswith("version:"):
            version = line.split(":", 1)[1].strip().strip('"').strip("'")
        elif line.startswith("compatible_runtime_range:"):
            compat_range = line.split(":", 1)[1].strip().strip('"').strip("'")

    return version, compat_range


class SkillSynchronizer:
    """Discovers installed skill and analyzes compatibility with runtime."""

    def __init__(self, skill_path_override: Optional[Path] = None):
        self.skill_path_override = skill_path_override

    def discover_skill_path(self) -> Optional[Path]:
        """Finds active skill directory in Antigravity global config or repo."""
        if self.skill_path_override:
            p = Path(self.skill_path_override).resolve()
            if (p / "SKILL.md").is_file():
                return p

        vinfo = get_version_info()
        if vinfo.skill_installation_path:
            p = Path(vinfo.skill_installation_path).resolve()
            if (p / "SKILL.md").is_file():
                return p

        # Fallback check
        repo_root = Path(__file__).resolve().parent.parent.parent
        repo_skill = repo_root / "skills" / "desktop-webview-reviewer"
        if repo_skill.exists() and (repo_skill / "SKILL.md").is_file():
            return repo_skill.resolve()

        return None

    def check_synchronization(self) -> SkillSyncStatus:
        """Evaluates compatibility between installed skill and runtime."""
        vinfo = get_version_info()
        runtime_ver_str = vinfo.product_version
        skill_dir = self.discover_skill_path()

        if not skill_dir:
            return SkillSyncStatus(
                skill_path=None,
                skill_version=None,
                compatible_runtime_range=None,
                runtime_version=runtime_ver_str,
                is_compatible=False,
                skill_update_required=True,
                runtime_update_required=False,
                diagnosis="Skill installation not found in global config or repository.",
            )

        skill_md = skill_dir / "SKILL.md"
        skill_ver, compat_range = _parse_skill_frontmatter(skill_md)

        # Default compatibility range if not specified
        if not compat_range:
            # Assume same major version compatibility (e.g. >=2.0.0,<3.0.0)
            try:
                parsed_runtime = Version(runtime_ver_str)
                compat_range = f">={parsed_runtime.major}.0.0,<{parsed_runtime.major + 1}.0.0"
            except InvalidVersion:
                compat_range = ">=2.0.0,<3.0.0"

        # Check compatibility using packaging
        is_compatible = True
        try:
            runtime_v = Version(runtime_ver_str)
            spec = SpecifierSet(compat_range)
            if runtime_v not in spec:
                is_compatible = False
        except (InvalidVersion, InvalidSpecifier):
            is_compatible = False

        # Check if updates are needed
        skill_update_req = False
        runtime_update_req = False

        if not is_compatible:
            try:
                runtime_v = Version(runtime_ver_str)
                if skill_ver:
                    skill_v = Version(skill_ver)
                    if runtime_v > skill_v:
                        skill_update_req = True
                    else:
                        runtime_update_req = True
            except InvalidVersion:
                skill_update_req = True

        diagnosis_lines = []
        if is_compatible:
            diagnosis_lines.append(
                f"Skill v{skill_ver or 'unknown'} is fully compatible with runtime v{runtime_ver_str}."
            )
        else:
            diagnosis_lines.append(
                f"Incompatible combination: Runtime v{runtime_ver_str} does not satisfy skill range '{compat_range}'."
            )
            if skill_update_req:
                diagnosis_lines.append("Recommendation: Update Antigravity skill package to match newer runtime.")
            elif runtime_update_req:
                diagnosis_lines.append("Recommendation: Update runtime package to satisfy skill requirements.")

        return SkillSyncStatus(
            skill_path=str(skill_dir),
            skill_version=skill_ver,
            compatible_runtime_range=compat_range,
            runtime_version=runtime_ver_str,
            is_compatible=is_compatible,
            skill_update_required=skill_update_req,
            runtime_update_required=runtime_update_req,
            diagnosis=" ".join(diagnosis_lines),
        )
