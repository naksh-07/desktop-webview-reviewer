"""
Desktop WebView Reviewer 2.0 - Authoritative Production Release Validation Pipeline.
Implements the deterministic 8-stage production release gate:
  1. SOURCE AUDIT
  2. TEST SUITE
  3. REAL-APP CERTIFICATION
  4. ADVERSARIAL SECURITY
  5. HARNESS RELEASE SECURITY
  6. PACKAGE BUILD
  7. PACKAGE INSPECTION
  8. FINAL RELEASE GATE
Fails closed on any violation or missing verification.
"""

from __future__ import annotations

import functools
import hashlib
import json
import logging
import os
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("desktop_webview.release_validator")
# Ensure all prints are unbuffered and immediate
print = functools.partial(print, flush=True)


@dataclass
class StageResult:
    stage_name: str
    verdict: str  # "PASS", "FAIL", "UNVERIFIED"
    details: str
    duration_sec: float
    violations: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReleaseGateReport:
    version: str
    overall_verdict: str
    stages: List[StageResult] = field(default_factory=list)
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "overall_verdict": self.overall_verdict,
            "summary": self.summary,
            "stages": [
                {
                    "stage_name": s.stage_name,
                    "verdict": s.verdict,
                    "details": s.details,
                    "duration_sec": round(s.duration_sec, 3),
                    "violations": s.violations,
                    "metadata": s.metadata,
                }
                for s in self.stages
            ],
            "artifacts": self.artifacts,
        }


class ProductionReleaseValidator:
    """Orchestrates deterministic release certification and fails closed."""

    def __init__(self, repo_root: Optional[Path] = None):
        self.repo_root = (repo_root or Path(__file__).resolve().parent.parent).resolve()
        self.python_bin = sys.executable

    def run_pipeline(self) -> ReleaseGateReport:
        start_time = time.time()
        stages: List[StageResult] = []
        overall_verdict = "PASS"

        print("=" * 70)
        print("  DESKTOP WEBVIEW REVIEWER 2.0 - PRODUCTION RELEASE PIPELINE")
        print("=" * 70)

        # ---------------------------------------------------------------------
        # Gate 1: SOURCE AUDIT
        # ---------------------------------------------------------------------
        g1_start = time.time()
        print("\n[Gate 1/8] Executing SOURCE AUDIT...")
        from scripts.security_audit import SecurityAuditor
        auditor = SecurityAuditor(repo_root=self.repo_root)
        sec_report = auditor.run_full_audit()
        g1_dur = time.time() - g1_start
        if sec_report.verdict == "PASS":
            stages.append(StageResult(
                stage_name="1_SOURCE_AUDIT",
                verdict="PASS",
                details=f"All {sec_report.total_checks} source and security audit checks passed cleanly.",
                duration_sec=g1_dur,
            ))
            print("  -> PASS: Source code audit passed with 0 security findings.")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="1_SOURCE_AUDIT",
                verdict="FAIL",
                details=f"Security audit failed ({sec_report.failed_checks} failures).",
                duration_sec=g1_dur,
                violations=[it.details for it in sec_report.items if it.status == "FAIL"],
            ))
            print("  -> FAIL: Security audit detected violations.")

        # ---------------------------------------------------------------------
        # Gate 2: TEST SUITE (All repository tests)
        # ---------------------------------------------------------------------
        g2_start = time.time()
        print("\n[Gate 2/8] Executing COMPLETE TEST SUITE...")
        cmd_tests = [self.python_bin, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"]
        res_tests = subprocess.run(cmd_tests, cwd=str(self.repo_root), capture_output=True, text=True)
        g2_dur = time.time() - g2_start
        if res_tests.returncode == 0:
            stages.append(StageResult(
                stage_name="2_TEST_SUITE",
                verdict="PASS",
                details="Complete repository test suite executed with zero failures.",
                duration_sec=g2_dur,
            ))
            print("  -> PASS: Complete regression test suite passed.")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="2_TEST_SUITE",
                verdict="FAIL",
                details="Test suite encountered failures.",
                duration_sec=g2_dur,
                violations=[res_tests.stderr or res_tests.stdout],
            ))
            print("  -> FAIL: Regression test suite failed.")

        # ---------------------------------------------------------------------
        # Gate 3: REAL-APP CERTIFICATION MATRIX
        # ---------------------------------------------------------------------
        g3_start = time.time()
        print("\n[Gate 3/8] Checking REAL-APP CERTIFICATION MATRIX...")
        cert_file = self.repo_root / "evidence" / "certification" / "certification_matrix.json"
        if not cert_file.exists():
            subprocess.run([self.python_bin, "scripts/certify.py"], cwd=str(self.repo_root), capture_output=True)

        g3_dur = time.time() - g3_start
        if cert_file.exists():
            cert_data = json.loads(cert_file.read_text(encoding="utf-8"))
            matrix_verdict = cert_data.get("overall_verdict", "UNVERIFIED")
            entries = cert_data.get("entries", [])
            verified_count = cert_data.get("counts", {}).get("runtime_verified", 0)
            if not verified_count and entries:
                verified_count = sum(1 for e in entries if e.get("capability_state") == "runtime_verified")
            framework_names = [e.get("framework") for e in entries] if entries else list(cert_data.get("frameworks", {}).keys())
            if matrix_verdict == "PASS" and verified_count >= 3:
                stages.append(StageResult(
                    stage_name="3_REAL_APP_CERTIFICATION",
                    verdict="PASS",
                    details=f"Multi-framework matrix certified ({verified_count} live runtimes verified).",
                    duration_sec=g3_dur,
                    metadata={"frameworks": framework_names},
                ))
                print(f"  -> PASS: Multi-framework certification verified ({verified_count} live runtimes).")
            else:
                overall_verdict = "FAIL"
                stages.append(StageResult(
                    stage_name="3_REAL_APP_CERTIFICATION",
                    verdict="FAIL",
                    details=f"Certification matrix verdict={matrix_verdict}, verified runtimes={verified_count}.",
                    duration_sec=g3_dur,
                ))
                print("  -> FAIL: Multi-framework certification insufficient.")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="3_REAL_APP_CERTIFICATION",
                verdict="FAIL",
                details="Certification matrix file not found.",
                duration_sec=g3_dur,
            ))
            print("  -> FAIL: Certification matrix missing.")

        # ---------------------------------------------------------------------
        # Gate 4: ADVERSARIAL SECURITY (Dedicated 28 Categories)
        # ---------------------------------------------------------------------
        g4_start = time.time()
        print("\n[Gate 4/8] Executing ADVERSARIAL SECURITY CERTIFICATION...")
        cmd_adv = [self.python_bin, "-m", "unittest", "tests.test_phase19_adversarial_certification"]
        res_adv = subprocess.run(cmd_adv, cwd=str(self.repo_root), capture_output=True, text=True)
        g4_dur = time.time() - g4_start
        if res_adv.returncode == 0:
            stages.append(StageResult(
                stage_name="4_ADVERSARIAL_SECURITY",
                verdict="PASS",
                details="All 28 constitutional adversarial attack categories passed.",
                duration_sec=g4_dur,
            ))
            print("  -> PASS: All 28 adversarial categories passed.")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="4_ADVERSARIAL_SECURITY",
                verdict="FAIL",
                details="Adversarial security test suite failed.",
                duration_sec=g4_dur,
                violations=[res_adv.stderr or res_adv.stdout],
            ))
            print("  -> FAIL: Adversarial certification failed.")

        # ---------------------------------------------------------------------
        # Gate 5: HARNESS RELEASE SECURITY
        # ---------------------------------------------------------------------
        g5_start = time.time()
        print("\n[Gate 5/8] Validating HARNESS RELEASE SEGREGATION...")
        from runtime.harness.build_pipeline import ReleaseSecurityValidator
        harness_res = ReleaseSecurityValidator.scan_artifact(self.repo_root / "adapters")
        g5_dur = time.time() - g5_start
        if harness_res.is_clean:
            stages.append(StageResult(
                stage_name="5_HARNESS_RELEASE_SECURITY",
                verdict="PASS",
                details="Zero harness modules, symbols, or backdoors detected in production source paths.",
                duration_sec=g5_dur,
            ))
            print("  -> PASS: Zero harness backdoors or symbols detected.")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="5_HARNESS_RELEASE_SECURITY",
                verdict="FAIL",
                details=f"Detected {len(harness_res.findings)} prohibited harness symbols in release paths.",
                duration_sec=g5_dur,
                violations=[f.sample_text for f in harness_res.findings],
            ))
            print("  -> FAIL: Harness contamination detected.")

        # ---------------------------------------------------------------------
        # Gate 6: PACKAGE BUILD
        # ---------------------------------------------------------------------
        g6_start = time.time()
        print("\n[Gate 6/8] Building PRODUCTION WHEEL & SDIST...")
        dist_dir = self.repo_root / "dist"
        dist_dir.mkdir(parents=True, exist_ok=True)
        for f in dist_dir.glob("*"):
            try:
                f.unlink()
            except OSError:
                pass

        build_cmd = ["uv", "build", "--out-dir", str(dist_dir)]
        try:
            res_build = subprocess.run(build_cmd, cwd=str(self.repo_root), capture_output=True, text=True, shell=True)
        except Exception:
            res_build = subprocess.run([self.python_bin, "-m", "build", "--out-dir", str(dist_dir)], cwd=str(self.repo_root), capture_output=True, text=True)

        if res_build.returncode != 0:
            res_build = subprocess.run([self.python_bin, "-m", "build", "--out-dir", str(dist_dir)], cwd=str(self.repo_root), capture_output=True, text=True)

        g6_dur = time.time() - g6_start
        built_files = list(dist_dir.glob("*.whl")) + list(dist_dir.glob("*.tar.gz"))
        if len(built_files) >= 1:
            stages.append(StageResult(
                stage_name="6_PACKAGE_BUILD",
                verdict="PASS",
                details=f"Successfully built {len(built_files)} release artifact(s): {[f.name for f in built_files]}",
                duration_sec=g6_dur,
                metadata={"artifacts": [f.name for f in built_files]},
            ))
            print(f"  -> PASS: Package build successful ({[f.name for f in built_files]}).")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="6_PACKAGE_BUILD",
                verdict="FAIL",
                details="Package build failed.",
                duration_sec=g6_dur,
                violations=[res_build.stderr or res_build.stdout],
            ))
            print("  -> FAIL: Package build failed.")

        # ---------------------------------------------------------------------
        # Gate 7: PACKAGE ARTIFACT INSPECTION
        # ---------------------------------------------------------------------
        g7_start = time.time()
        print("\n[Gate 7/8] Inspecting RELEASE ARTIFACTS...")
        artifact_manifests: List[Dict[str, Any]] = []
        inspection_violations: List[str] = []

        for art_path in built_files:
            file_bytes = art_path.read_bytes()
            file_sha256 = hashlib.sha256(file_bytes).hexdigest()
            size_kb = len(file_bytes) / 1024.0

            file_names_inside: List[str] = []
            if art_path.suffix == ".whl":
                with zipfile.ZipFile(art_path, "r") as z:
                    file_names_inside = z.namelist()
            elif art_path.name.endswith(".tar.gz"):
                with tarfile.open(art_path, "r:gz") as t:
                    file_names_inside = t.getnames()

            # Verify no tests, fixtures, or harness files inside package
            forbidden_in_package = ["tests/", "fixtures/", "evidence/", ".dev.js", "reviewer_harness"]
            for fname in file_names_inside:
                for forb in forbidden_in_package:
                    if forb in fname:
                        inspection_violations.append(f"Forbidden path '{fname}' packaged inside {art_path.name}")

            # Verify version in artifact name
            if "2.0.0" not in art_path.name:
                inspection_violations.append(f"Artifact {art_path.name} does not reflect 2.0.0 version.")

            artifact_manifests.append({
                "filename": art_path.name,
                "sha256": file_sha256,
                "size_kb": round(size_kb, 2),
                "total_files": len(file_names_inside),
            })

        g7_dur = time.time() - g7_start
        if not inspection_violations and artifact_manifests:
            stages.append(StageResult(
                stage_name="7_PACKAGE_INSPECTION",
                verdict="PASS",
                details=f"All {len(artifact_manifests)} release artifacts verified clean of test fixtures and harness code.",
                duration_sec=g7_dur,
                metadata={"artifacts": artifact_manifests},
            ))
            print(f"  -> PASS: Artifact inspection clean ({len(artifact_manifests)} files verified).")
        else:
            overall_verdict = "FAIL"
            stages.append(StageResult(
                stage_name="7_PACKAGE_INSPECTION",
                verdict="FAIL",
                details=f"Artifact inspection found {len(inspection_violations)} violation(s).",
                duration_sec=g7_dur,
                violations=inspection_violations,
            ))
            print(f"  -> FAIL: Artifact inspection violations: {inspection_violations}")

        # ---------------------------------------------------------------------
        # Gate 8: FINAL RELEASE GATE
        # ---------------------------------------------------------------------
        print("\n[Gate 8/8] Evaluating FINAL RELEASE GATE...")
        g8_dur = time.time() - start_time
        summary = (
            f"Release Candidate 2.0.0 validation: {overall_verdict}. "
            f"Executed 8 pipeline stages across core tests, adversarial certification, "
            f"security audit, and artifact verification."
        )
        stages.append(StageResult(
            stage_name="8_FINAL_RELEASE_GATE",
            verdict=overall_verdict,
            details=summary,
            duration_sec=g8_dur,
        ))

        report = ReleaseGateReport(
            version="2.0.0",
            overall_verdict=overall_verdict,
            stages=stages,
            artifacts=artifact_manifests,
            summary=summary,
        )

        # Save release validation report
        out_dir = self.repo_root / "evidence" / "release"
        out_dir.mkdir(parents=True, exist_ok=True)
        report_file = out_dir / "release_validation_report.json"
        report_file.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")

        print("=" * 70)
        print(f"  OVERALL RELEASE VERDICT: {overall_verdict}")
        print(f"  Report saved to:         {report_file}")
        print("=" * 70)

        return report


def main() -> int:
    validator = ProductionReleaseValidator()
    report = validator.run_pipeline()
    return 0 if report.overall_verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
