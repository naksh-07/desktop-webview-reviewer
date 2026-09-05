"""
Build Mode Management & Release CI Security Gate (Architecture H).
Enforces strict segregation across DEV, REVIEW, and RELEASE build modes.
Scans release artifacts for harness modules, endpoints, IPC, symbols, and markers.
Fails closed if any harness trace is detected.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any, Set

from runtime.harness_contracts import (
    BuildMode,
    HarnessSecurityViolationException,
    HarnessSecurityValidator,
)

# Forbidden tokens and identifiers in production release artifacts
FORBIDDEN_RELEASE_PATTERNS = [
    (re.compile(r"reviewer_harness\.", re.IGNORECASE), "HARNESS_MODULE_NAME"),
    (re.compile(r"ReviewerHarness\.cs", re.IGNORECASE), "HARNESS_MODULE_NAME"),
    (re.compile(r"\.reviewer_harness\.json"), "HARNESS_MANIFEST_FILE"),
    (re.compile(r"/harness/v1/(handshake|lifecycle|diagnostics|fixture|fault)"), "HARNESS_ENDPOINT"),
    (re.compile(r"REVIEWER_HARNESS_DEV_ONLY"), "HARNESS_DEV_MARKER"),
    (re.compile(r"\b(initReviewerHarness|init_reviewer_harness|ReviewerHarness\.Initialize)\b"), "HARNESS_SYMBOL"),
    (re.compile(r"\b(ENABLE_HARNESS|ENABLE_REVIEWER_HARNESS|--enable-reviewer-harness)\b"), "FORBIDDEN_PRODUCTION_SWITCH"),
]

# File extensions checked for text patterns
SCANNABLE_TEXT_EXTENSIONS = {
    ".js", ".mjs", ".cjs", ".ts", ".html", ".htm", ".json",
    ".cs", ".py", ".cpp", ".c", ".h", ".xaml", ".xml", ".txt", ".map"
}


@dataclass
class ReleaseScanFinding:
    """Individual security violation identified in a release artifact."""
    relative_path: str
    finding_type: str
    pattern: str
    sample_text: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "relative_path": self.relative_path,
            "finding_type": self.finding_type,
            "pattern": self.pattern,
            "sample_text": self.sample_text[:200],
        }


@dataclass
class ReleaseValidationResult:
    """Forensic report of release artifact security inspection."""
    artifact_path: str
    verdict: str  # "PASS" | "FAIL"
    findings: List[ReleaseScanFinding] = field(default_factory=list)
    scanned_files_count: int = 0
    build_mode: BuildMode = BuildMode.RELEASE

    @property
    def is_clean(self) -> bool:
        return len(self.findings) == 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "artifact_path": self.artifact_path,
            "verdict": self.verdict,
            "is_clean": self.is_clean,
            "findings_count": len(self.findings),
            "findings": [f.to_dict() for f in self.findings],
            "scanned_files_count": self.scanned_files_count,
            "build_mode": self.build_mode.value,
        }


class ReleaseSecurityValidator:
    """
    Independent CI gate verifying that release production artifacts
    have zero harness code, endpoints, bridges, symbols, or dormant switches.
    """

    @classmethod
    def scan_artifact(cls, target_path: str | Path) -> ReleaseValidationResult:
        root = Path(target_path).resolve()
        if not root.exists():
            raise FileNotFoundError(f"Target release artifact not found: {target_path}")

        findings: List[ReleaseScanFinding] = []
        scanned_count = 0

        files_to_scan: List[Path] = []
        if root.is_file():
            files_to_scan.append(root)
        else:
            for p in root.rglob("*"):
                if p.is_file():
                    files_to_scan.append(p)

        for file_path in files_to_scan:
            scanned_count += 1
            rel_str = str(file_path.relative_to(root)) if root.is_dir() else file_path.name

            # 1. Filename scan
            for regex, ftype in FORBIDDEN_RELEASE_PATTERNS:
                if regex.search(file_path.name):
                    findings.append(ReleaseScanFinding(
                        relative_path=rel_str,
                        finding_type=ftype,
                        pattern=regex.pattern,
                        sample_text=f"Prohibited filename: {file_path.name}",
                    ))

            # 2. Content scan for text/script files
            if file_path.suffix.lower() in SCANNABLE_TEXT_EXTENSIONS:
                try:
                    content = file_path.read_text(encoding="utf-8", errors="ignore")
                    for regex, ftype in FORBIDDEN_RELEASE_PATTERNS:
                        match = regex.search(content)
                        if match:
                            start = max(0, match.start() - 30)
                            end = min(len(content), match.end() + 30)
                            sample = content[start:end].replace("\n", " ").strip()
                            findings.append(ReleaseScanFinding(
                                relative_path=rel_str,
                                finding_type=ftype,
                                pattern=regex.pattern,
                                sample_text=sample,
                            ))
                except Exception:
                    pass

        verdict = "FAIL" if findings else "PASS"
        return ReleaseValidationResult(
            artifact_path=str(root),
            verdict=verdict,
            findings=findings,
            scanned_files_count=scanned_count,
            build_mode=BuildMode.RELEASE,
        )
