"""
Evidence collection, screenshot hashing, and artifact packaging.
"""

import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

from .models import EngineInfo, EvidenceReport, Target
from .session import CDPSession

logger = logging.getLogger("desktop_webview.evidence")

PNG_MAGIC_BYTES = b"\x89PNG\r\n\x1a\n"


class EvidenceCollector:
    """Collects forensic verification evidence (DOM, screenshot, console, assertions)."""

    def __init__(self, session: CDPSession, engine_info: EngineInfo):
        self.session = session
        self.engine_info = engine_info

    async def capture_screenshot_file(self, output_path: str = "screenshot.png") -> str:
        """Captures page screenshot, validates PNG magic bytes, calculates SHA-256, and writes to disk."""
        data = await self.session.capture_screenshot(format="png")
        
        # Validate PNG header
        if not data.startswith(PNG_MAGIC_BYTES):
            raise ValueError(f"Invalid PNG data captured: missing PNG magic header. Got: {data[:8].hex()}")

        # Compute SHA-256
        sha256_hash = hashlib.sha256(data).hexdigest()

        # Write to disk
        with open(output_path, "wb") as f:
            f.write(data)

        logger.info(f"Screenshot saved to {output_path} ({len(data)} bytes, SHA-256: {sha256_hash})")
        return sha256_hash

    async def capture_dom_snapshot(self) -> str:
        """Retrieves outerHTML of entire document."""
        js = "document.documentElement ? document.documentElement.outerHTML : ''"
        html = await self.session.evaluate_js(js)
        return str(html) if html else ""

    async def build_report(
        self,
        screenshot_path: Optional[str] = None,
        assertions: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Any]] = None,
        process_ownership: Optional[Any] = None,
        diagnostics: Optional[Dict[str, Any]] = None,
        verification_level: Optional[Any] = None,
        extra_metadata: Optional[Dict[str, Any]] = None
    ) -> EvidenceReport:
        """Constructs an EvidenceReport dataclass instance."""
        dom_snapshot = await self.capture_dom_snapshot()
        
        sha256 = None
        if screenshot_path and os.path.exists(screenshot_path):
            with open(screenshot_path, "rb") as f:
                sha256 = hashlib.sha256(f.read()).hexdigest()

        from .models import VerificationLevel
        lvl = verification_level or self.engine_info.verification_level or VerificationLevel.RUNTIME_VERIFIED

        report = EvidenceReport(
            target=self.session.target,
            engine_info=self.engine_info,
            framework=self.engine_info.framework or self.session.target.framework,
            engine=self.engine_info.engine or self.session.target.engine,
            verification_level=lvl,
            dom_snapshot=dom_snapshot,
            screenshot_path=screenshot_path,
            screenshot_sha256=sha256,
            console_messages=list(self.session.console_events),
            state_assertions=assertions or [],
            actions=actions or [],
            process_ownership=process_ownership,
            diagnostics=diagnostics or {},
            metadata=extra_metadata or {
                "collection_time": time.time(),
                "collection_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
        )
        return report

    @staticmethod
    def save_report_json(report: EvidenceReport, output_file: str = "evidence.json") -> None:
        """Saves evidence report to JSON file."""
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(report.to_dict(), f, indent=2)
        logger.info(f"Evidence report saved to {output_file}")

