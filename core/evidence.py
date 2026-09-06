"""
Evidence collection, screenshot hashing, provenance tracking, and artifact packaging.
"""

import hashlib
import json
import logging
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple

from .models import (
    EngineInfo,
    EvidenceReport,
    ProcessOwnership,
    ScreenshotMetadata,
    ScreenshotType,
    Target,
    Verdict,
    VerificationLevel,
    WindowForensics
)
from .session import CDPSession
from .window_forensics import WindowForensicsEngine

logger = logging.getLogger("desktop_webview.evidence")

PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"


class EvidenceCollector:
    """Collects forensic verification evidence (DOM, screenshot provenance, console, assertions, verdicts)."""

    def __init__(self, session: CDPSession, engine_info: EngineInfo):
        self.session = session
        self.engine_info = engine_info
        self.screenshots: Dict[str, ScreenshotMetadata] = {}

    async def capture_cdp_screenshot(
        self, output_path: str = "screenshot_cdp.png", key: str = "webview"
    ) -> Tuple[str, ScreenshotMetadata]:
        """
        Captures webview viewport screenshot via CDP Page.captureScreenshot.
        Validates PNG magic header, computes SHA-256 hash, and registers provenance metadata.
        NOTE: A CDP screenshot alone is NOT proof that the native GUI was visible on the desktop.
        """
        data = await self.session.capture_screenshot(format="png")

        # Validate PNG header
        if not data.startswith(PNG_MAGIC_BYTES):
            raise ValueError(f"Invalid PNG data captured: missing PNG magic header. Got: {data[:8].hex()}")

        # Compute SHA-256
        sha256_hash = hashlib.sha256(data).hexdigest()

        # Write to disk
        os.makedirs(os.path.dirname(os.path.abspath(output_path)) or ".", exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(data)

        meta = ScreenshotMetadata(
            screenshot_type=ScreenshotType.CDP_PAGE_CAPTURE,
            screenshot_hash=sha256_hash,
            path=output_path,
            source="cdp_page_capture (internal webview rendering surface, not native desktop OS capture)",
            dimensions={},
            timestamp=time.time()
        )
        self.screenshots[key] = meta
        logger.info(f"CDP Webview screenshot saved to {output_path} ({len(data)} bytes, SHA-256: {sha256_hash})")
        return sha256_hash, meta

    async def capture_screenshot_file(
        self, output_path: str = "screenshot.png", screenshot_type: ScreenshotType = ScreenshotType.CDP_PAGE_CAPTURE
    ) -> str:
        """
        Compatibility method for existing callers.
        Captures page screenshot, calculates SHA-256, and registers provenance.
        """
        sha256_hash, _ = await self.capture_cdp_screenshot(output_path=output_path, key="primary")
        return sha256_hash

    def capture_native_screenshot(
        self, hwnd: int, output_path: str = "screenshot_native.png", key: str = "native"
    ) -> Tuple[bool, str, Optional[ScreenshotMetadata]]:
        """
        Captures actual OS desktop window surface using Win32 GDI PrintWindow.
        Registers native desktop screenshot provenance and computes SHA-256.
        """
        success, sha256_hash, err = WindowForensicsEngine.capture_native_window_screenshot(hwnd, output_path)
        if not success:
            logger.warning(f"Could not capture native OS window screenshot: {err}")
            return False, "", None

        meta = ScreenshotMetadata(
            screenshot_type=ScreenshotType.NATIVE_DESKTOP,
            screenshot_hash=sha256_hash,
            path=output_path,
            source=f"win32_gdi_hwnd (HWND: {hwnd})",
            dimensions={},
            timestamp=time.time()
        )
        self.screenshots[key] = meta
        logger.info(f"Native desktop screenshot saved to {output_path} (SHA-256: {sha256_hash})")
        return True, sha256_hash, meta

    async def capture_dom_snapshot(self) -> str:
        """Retrieves outerHTML of entire document."""
        js = "document.documentElement ? document.documentElement.outerHTML : ''"
        html = await self.session.evaluate_js(js)
        return str(html) if html else ""

    @staticmethod
    def evaluate_verdict(
        window_forensics: Optional[WindowForensics],
        assertions: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        process_ownership: Optional[ProcessOwnership] = None,
        screenshots: Optional[Dict[str, ScreenshotMetadata]] = None,
        require_visible_gui: bool = True,
        user_confirmation: bool = False,
        input_delivery_verified: bool = False,
        execution_mode: str = "automated"
    ) -> Tuple[Verdict, str]:
        """
        Evaluates the forensic verification state machine to produce PASS, FAIL, or UNVERIFIED.

        Rules:
        1. FAIL: Explicit assertion failure or runtime execution crash.
        2. UNVERIFIED: Missing visible native GUI window, 0x0 geometry, iconic/cloaked,
           mismatched PID/port, missing visual proofs, or pending human confirmation in interactive mode.
        3. PASS: Visible real GUI window confirmed + matched PID + all assertions passed.
        """
        # 1. Check Assertions
        if assertions:
            failed_assertions = [a for a in assertions if not a.get("passed", False)]
            if failed_assertions:
                reasons = [a.get("description", "Unknown assertion") for a in failed_assertions]
                return Verdict.FAIL, f"Assertion failed: {'; '.join(reasons)}"

        # 2. Check Window Forensics & GUI Identity
        if require_visible_gui:
            if not window_forensics:
                return (
                    Verdict.UNVERIFIED,
                    "No native OS window forensics available; visible desktop GUI could not be proven."
                )

            if not window_forensics.hwnd:
                return (
                    Verdict.UNVERIFIED,
                    "No top-level window handle (HWND) found for application process tree."
                )

            if not window_forensics.window_visible:
                return (
                    Verdict.UNVERIFIED,
                    f"Application window (HWND {window_forensics.hwnd}) is not visible on desktop (IsWindowVisible=False)."
                )

            if window_forensics.is_iconic:
                return (
                    Verdict.UNVERIFIED,
                    f"Application window (HWND {window_forensics.hwnd}) is minimized (IsIconic=True)."
                )

            if window_forensics.is_cloaked:
                return (
                    Verdict.UNVERIFIED,
                    f"Application window (HWND {window_forensics.hwnd}) is cloaked / hidden by system/shell (DWMWA_CLOAKED)."
                )

            geom = window_forensics.geometry or {}
            width = geom.get("width", 0)
            height = geom.get("height", 0)
            if width < 30 or height < 30:
                return (
                    Verdict.UNVERIFIED,
                    f"Application window has non-renderable or zero geometry ({width}x{height})."
                )

            if not window_forensics.hwnd_pid_matched:
                return (
                    Verdict.UNVERIFIED,
                    f"Window owning PID ({window_forensics.pid}) does not match expected application process tree."
                )

            if not window_forensics.foreground_match:
                return (
                    Verdict.UNVERIFIED,
                    f"Application window (HWND {window_forensics.hwnd}) is not the foreground window (Foreground HWND {window_forensics.foreground_hwnd})."
                )

            if window_forensics.intersection_area <= 0:
                return (
                    Verdict.UNVERIFIED,
                    f"Application window has no visible intersection with the monitor (intersection area {window_forensics.intersection_area})."
                )

        if require_visible_gui:
            # Interactive mode requires explicit human reviewer confirmation
            if execution_mode == "interactive" and not user_confirmation:
                return (
                    Verdict.UNVERIFIED,
                    "Automated proofs passed, but human reviewer confirmation is pending."
                )
            elif not user_confirmation and execution_mode not in ("automated", "runtime"):
                return (
                    Verdict.UNVERIFIED,
                    "User confirmation of window visibility is missing or False."
                )

            if not input_delivery_verified and (assertions or actions):
                return (
                    Verdict.UNVERIFIED,
                    "Input delivery to the application window was not verified."
                )

            if screenshots:
                has_desktop = "desktop" in screenshots
                has_native = "native" in screenshots
                has_webview = "webview" in screenshots or "primary" in screenshots
                if not (has_desktop and has_native and has_webview):
                    return (
                        Verdict.UNVERIFIED,
                        f"Missing required screenshot proofs (desktop: {has_desktop}, native: {has_native}, webview: {has_webview})."
                    )

        # 3. Check Screenshot Provenance
        if screenshots:
            for sname, smeta in screenshots.items():
                if smeta.screenshot_type == ScreenshotType.CDP_PAGE_CAPTURE:
                    # CDP captures are valid for webview inspection, but cannot substitute for missing GUI
                    pass

        # 4. All forensic checks and assertions succeeded
        return (
            Verdict.PASS,
            "Verified live visible desktop GUI window and matching CDP target with all assertions passing."
        )

    async def build_report(
        self,
        screenshot_path: Optional[str] = None,
        assertions: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Any]] = None,
        process_ownership: Optional[ProcessOwnership] = None,
        window_forensics: Optional[WindowForensics] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        verification_level: Optional[Any] = None,
        session_id: Optional[str] = None,
        extra_metadata: Optional[Dict[str, Any]] = None,
        user_confirmation: bool = True,
        input_delivery_verified: bool = True,
        desktop_capture_path: Optional[str] = None,
        native_capture_path: Optional[str] = None,
        webview_capture_path: Optional[str] = None,
        execution_mode: str = "automated"
    ) -> EvidenceReport:
        """Constructs a forensically hardened EvidenceReport instance."""
        dom_snapshot = await self.capture_dom_snapshot()

        # Hash screenshot if provided directly
        sha256 = None
        if screenshot_path and os.path.exists(screenshot_path):
            with open(screenshot_path, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()
            if "primary" not in self.screenshots:
                self.screenshots["primary"] = ScreenshotMetadata(
                    screenshot_type=ScreenshotType.CDP_PAGE_CAPTURE,
                    screenshot_hash=sha256,
                    path=screenshot_path,
                    source="cdp_page_capture",
                    timestamp=time.time()
                )

        # Evaluate Verdict
        verdict, verdict_reason = self.evaluate_verdict(
            window_forensics=window_forensics,
            assertions=assertions,
            process_ownership=process_ownership,
            screenshots=self.screenshots,
            require_visible_gui=True,
            user_confirmation=user_confirmation,
            input_delivery_verified=input_delivery_verified,
            execution_mode=execution_mode
        )

        lvl = verification_level or self.engine_info.verification_level or VerificationLevel.RUNTIME_VERIFIED

        report = EvidenceReport(
            target=self.session.target,
            engine_info=self.engine_info,
            session_id=session_id or f"session_{uuid.uuid4().hex[:12]}",
            framework=self.engine_info.framework or self.session.target.framework,
            engine=self.engine_info.engine or self.session.target.engine,
            verdict=verdict,
            verdict_reason=verdict_reason,
            verification_level=lvl,
            window_forensics=window_forensics,
            screenshots=dict(self.screenshots),
            dom_snapshot=dom_snapshot,
            screenshot_path=screenshot_path or (self.screenshots["primary"].path if "primary" in self.screenshots else None),
            screenshot_sha256=sha256 or (self.screenshots["primary"].screenshot_hash if "primary" in self.screenshots else None),
            console_messages=list(self.session.console_events),
            state_assertions=assertions or [],
            actions=actions or [],
            process_ownership=process_ownership,
            diagnostics=diagnostics or {},
            metadata=extra_metadata or {
                "collection_time": time.time(),
                "collection_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            },
            user_confirmation=user_confirmation,
            input_delivery_verified=input_delivery_verified,
            desktop_capture_path=desktop_capture_path,
            native_capture_path=native_capture_path,
            webview_capture_path=webview_capture_path
        )
        return report

    @staticmethod
    def save_report_json(report: EvidenceReport, output_file: str = "evidence.json") -> None:
        """Saves evidence report to JSON file with extended forensic schema."""
        os.makedirs(os.path.dirname(os.path.abspath(output_file)) or ".", exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info(f"Evidence report saved to {output_file} (Verdict: {report.verdict.value})")
