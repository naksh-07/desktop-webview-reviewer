"""
Project and Framework Detector for Reviewer Test Harness (Architecture H).
Inspects application project structures to deterministically identify Electron,
WebView2, or QtWebEngine targets with confidence scores and entry points.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

from runtime.harness.adapters import get_adapter_for_framework


@dataclass(frozen=True)
class DetectionResult:
    """Structured forensic outcome of project framework detection."""
    framework: Optional[str]
    confidence: float
    detected_indicators: List[str] = field(default_factory=list)
    entry_points: List[str] = field(default_factory=list)
    adapter: Optional[str] = None
    supported_capabilities: Dict[str, str] = field(default_factory=dict)
    is_ambiguous: bool = False
    is_supported: bool = False
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "confidence": self.confidence,
            "detected_indicators": self.detected_indicators,
            "entry_points": self.entry_points,
            "adapter": self.adapter,
            "supported_capabilities": self.supported_capabilities,
            "is_ambiguous": self.is_ambiguous,
            "is_supported": self.is_supported,
            "reasons": self.reasons,
        }


class ProjectDetector:
    """
    Inspects project trees for genuine framework indicators.
    Avoids false positives from casual mentions in documentation or comments.
    """

    @classmethod
    def detect(cls, project_dir: str | Path) -> DetectionResult:
        root = Path(project_dir).resolve()
        if not root.exists() or not root.is_dir():
            return DetectionResult(
                framework=None,
                confidence=0.0,
                reasons=[f"Project directory does not exist or is not a directory: '{project_dir}'"],
            )

        electron_score, electron_indicators, electron_entries = cls._probe_electron(root)
        webview2_score, webview2_indicators, webview2_entries = cls._probe_webview2(root)
        qt_score, qt_indicators, qt_entries = cls._probe_qt(root)

        scores = [
            ("electron", electron_score, electron_indicators, electron_entries),
            ("webview2", webview2_score, webview2_indicators, webview2_entries),
            ("qt", qt_score, qt_indicators, qt_entries),
        ]

        # Sort by confidence descending
        scores.sort(key=lambda s: s[1], reverse=True)
        top_name, top_score, top_indicators, top_entries = scores[0]
        second_name, second_score, _, _ = scores[1]

        # Ambiguity check
        if top_score > 0.4 and second_score > 0.4 and abs(top_score - second_score) < 0.15:
            return DetectionResult(
                framework=None,
                confidence=top_score,
                is_ambiguous=True,
                is_supported=False,
                reasons=[
                    f"Ambiguous project indicators between '{top_name}' ({top_score:.2f}) and '{second_name}' ({second_score:.2f})."
                ],
            )

        if top_score < 0.35:
            return DetectionResult(
                framework=None,
                confidence=top_score,
                is_supported=False,
                reasons=["No supported desktop webview framework recognized (Electron, WebView2, or QtWebEngine)."],
            )

        adapter = get_adapter_for_framework(top_name)
        caps = {}
        if adapter:
            caps = {k: v.value for k, v in adapter.get_supported_capabilities().items()}

        return DetectionResult(
            framework=top_name,
            confidence=round(top_score, 2),
            detected_indicators=top_indicators,
            entry_points=top_entries,
            adapter=adapter.adapter_name if adapter else None,
            supported_capabilities=caps,
            is_supported=True,
            reasons=[f"Successfully detected {top_name} application."],
        )

    @classmethod
    def _probe_electron(cls, root: Path) -> tuple[float, list[str], list[str]]:
        indicators: list[str] = []
        entry_points: list[str] = []
        score = 0.0

        pkg_path = root / "package.json"
        if pkg_path.exists():
            indicators.append("package.json present")
            score += 0.2
            try:
                data = json.loads(pkg_path.read_text(encoding="utf-8", errors="ignore"))
                deps = data.get("dependencies", {})
                dev_deps = data.get("devDependencies", {})
                if "electron" in deps or "electron" in dev_deps:
                    indicators.append("electron declared in package dependencies")
                    score += 0.5

                main_entry = data.get("main")
                if main_entry:
                    main_file = root / main_entry
                    if main_file.exists():
                        indicators.append(f"entry point in package.json main: {main_entry}")
                        entry_points.append(str(main_file.relative_to(root)))
                        score += 0.2
            except Exception:
                pass

        for candidate in ["main.js", "index.js", "src/main.js", "src/index.js", "app.js"]:
            p = root / candidate
            if p.exists() and str(p.relative_to(root)) not in entry_points:
                try:
                    txt = p.read_text(encoding="utf-8", errors="ignore")[:3000]
                    if "require('electron')" in txt or 'require("electron")' in txt or "from 'electron'" in txt or 'from "electron"' in txt:
                        indicators.append(f"electron require/import in {candidate}")
                        entry_points.append(candidate)
                        score += 0.2
                except Exception:
                    pass

        return min(score, 1.0), indicators, entry_points

    @classmethod
    def _probe_webview2(cls, root: Path) -> tuple[float, list[str], list[str]]:
        indicators: list[str] = []
        entry_points: list[str] = []
        score = 0.0

        csproj_files = list(root.glob("*.csproj")) + list(root.glob("*/*.csproj"))
        for csproj in csproj_files:
            indicators.append(f"Found project file: {csproj.name}")
            score += 0.2
            try:
                content = csproj.read_text(encoding="utf-8", errors="ignore")
                if "Microsoft.Web.WebView2" in content:
                    indicators.append(f"Microsoft.Web.WebView2 reference in {csproj.name}")
                    score += 0.5
            except Exception:
                pass

        for cs_file in root.rglob("*.cs"):
            if "obj" in cs_file.parts or "bin" in cs_file.parts:
                continue
            try:
                txt = cs_file.read_text(encoding="utf-8", errors="ignore")[:3000]
                if "Microsoft.Web.WebView2" in txt or "CoreWebView2" in txt:
                    rel = str(cs_file.relative_to(root))
                    indicators.append(f"CoreWebView2 reference in {rel}")
                    entry_points.append(rel)
                    score += 0.3
                    break
            except Exception:
                pass

        return min(score, 1.0), indicators, entry_points

    @classmethod
    def _probe_qt(cls, root: Path) -> tuple[float, list[str], list[str]]:
        indicators: list[str] = []
        entry_points: list[str] = []
        score = 0.0

        for req_name in ["requirements.txt", "pyproject.toml", "setup.py"]:
            req_file = root / req_name
            if req_file.exists():
                try:
                    txt = req_file.read_text(encoding="utf-8", errors="ignore")
                    for token in ["PyQt5", "PyQt6", "PySide2", "PySide6", "PyQt6-WebEngine", "PyQt5-WebEngine"]:
                        if token.lower() in txt.lower():
                            indicators.append(f"{token} declared in {req_name}")
                            score += 0.4
                            break
                except Exception:
                    pass

        for py_file in root.glob("*.py"):
            try:
                txt = py_file.read_text(encoding="utf-8", errors="ignore")[:3000]
                if any(kw in txt for kw in ["QtWebEngineWidgets", "QWebEngineView", "QWebEnginePage"]):
                    rel = str(py_file.relative_to(root))
                    indicators.append(f"QtWebEngine import in {rel}")
                    entry_points.append(rel)
                    score += 0.5
            except Exception:
                pass

        return min(score, 1.0), indicators, entry_points
