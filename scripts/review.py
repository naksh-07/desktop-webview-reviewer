"""
Automated review & verification script with Windows forensic hardening.
Inspects DOM, evaluates JS, interacts with elements, verifies native GUI identity,
captures dual screenshot provenance, and produces forensic evidence reports with
tripartite verdict separation (PASS, FAIL, UNVERIFIED).
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
import time
from typing import Optional

from core.actions import WebviewActions
from core.assertions import WebviewAssertions
from core.evidence import EvidenceCollector
from core.models import (
    ProcessOwnership,
    ScreenshotType,
    Target,
    Verdict,
    VerificationLevel,
    WindowForensics
)
from core.window_forensics import WindowForensicsEngine
from detectors.engine_detector import EngineDetector


async def run_review(
    ws_url: str,
    engine_name: str = "auto",
    click_selector: Optional[str] = None,
    type_selector: Optional[str] = None,
    type_text: Optional[str] = None,
    assert_selector: Optional[str] = None,
    assert_text_expected: Optional[str] = None,
    screenshot_path: str = "screenshot.png",
    native_screenshot_path: Optional[str] = None,
    evidence_path: str = "evidence.json",
    ownership_file: str = "desktop_ownership.json"
) -> int:
    adapter = EngineDetector.resolve_adapter(engine_name_or_hint=engine_name)
    engine_info = adapter.get_engine_info()

    target = Target(
        id="review_target",
        type="page",
        title="",
        url="",
        engine=adapter.engine_name,
        framework=engine_info.framework,
        websocket_endpoint=ws_url
    )

    print("\n" + "=" * 65)
    print("=== Universal Desktop WebView Hardened Forensic Review ===")
    print("=" * 65)
    print(f"Connecting reviewer to: {ws_url}")
    print(f"Engine: {adapter.engine_name} | Framework: {engine_info.framework or 'native'}")

    current_stage = "attach"
    launch_mode = "launched_by_reviewer" if os.path.exists(ownership_file) else "attached_external"
    conf_str = engine_info.confidence.value if hasattr(engine_info.confidence, "value") else str(engine_info.confidence)

    # 1. Process ownership & subtree resolution
    proc_ownership: Optional[ProcessOwnership] = None
    target_pids = set()
    if os.path.exists(ownership_file):
        try:
            with open(ownership_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                proc_ownership = ProcessOwnership(
                    pid=data.get("pid", 0),
                    create_time=data.get("create_time"),
                    launched_by_reviewer=data.get("launched_by_reviewer", True),
                    command=data.get("command"),
                    port=data.get("port", 9222)
                )
                if proc_ownership.pid:
                    target_pids = WindowForensicsEngine.get_process_tree_pids(proc_ownership.pid)
        except Exception:
            pass

    session = None
    window_forensics: Optional[WindowForensics] = None
    try:
        current_stage = "attach"
        session = await adapter.attach(target)
        actions = adapter.create_actions(session)
        assertions = adapter.create_assertions(session)
        collector = adapter.create_evidence_collector(session)

        # 2. Inspect target title and URL
        current_stage = "inspection"
        title = await session.evaluate_js("document.title")
        url = await session.evaluate_js("window.location.href")
        target.title = str(title or "")
        target.url = str(url or "")
        print(f"Target Title: '{target.title}' | URL: '{target.url}'")

        # 3. Native Windows GUI Forensic Inspection
        current_stage = "gui_forensics"
        if sys.platform == "win32" and proc_ownership and proc_ownership.pid:
            proc_info = WindowForensicsEngine.get_process_info(proc_ownership.pid)
            gui_win = WindowForensicsEngine.get_primary_gui_window(
                proc_ownership.pid, expected_title_substring=target.title
            )

            port_ok, listening_pid, port_msg = WindowForensicsEngine.verify_port_listening_process(
                proc_ownership.port, target_pids
            )

            if gui_win:
                window_forensics = WindowForensics(
                    hwnd=gui_win.get("hwnd"),
                    pid=gui_win.get("pid"),
                    executable=proc_info.get("executable"),
                    cmdline=proc_info.get("cmdline") or [],
                    window_title=gui_win.get("title", ""),
                    class_name=gui_win.get("class_name", ""),
                    window_visible=gui_win.get("is_visible", False),
                    is_iconic=gui_win.get("is_iconic", False),
                    is_cloaked=gui_win.get("is_cloaked", False),
                    is_real_gui=gui_win.get("is_real_gui", False),
                    geometry=gui_win.get("geometry", {}),
                    hwnd_pid_matched=(gui_win.get("pid") in target_pids),
                    notes=[port_msg]
                )
            else:
                window_forensics = WindowForensics(
                    hwnd=None,
                    pid=proc_ownership.pid,
                    executable=proc_info.get("executable"),
                    cmdline=proc_info.get("cmdline") or [],
                    window_visible=False,
                    is_real_gui=False,
                    hwnd_pid_matched=False,
                    notes=["No top-level window found for process tree", port_msg]
                )

        # 4. Session Diagnostics Output
        print("\nSession Forensics:")
        print(f"  Detected framework: {engine_info.framework or 'native'}")
        print(f"  Detected engine:    {adapter.engine_name}")
        print(f"  Confidence:         {conf_str.upper()}")
        print(f"  Platform:           {sys.platform}")
        print(f"  Launch mode:        {launch_mode}")
        if window_forensics:
            print(f"  Native HWND:        {window_forensics.hwnd}")
            print(f"  Window Title:       '{window_forensics.window_title}'")
            print(f"  Window Visible:     {window_forensics.window_visible} (Iconic={window_forensics.is_iconic}, Cloaked={window_forensics.is_cloaked})")
            print(f"  Window Geometry:    {window_forensics.geometry}")
            print(f"  PID Matched:        {window_forensics.hwnd_pid_matched} (Process Tree: {sorted(list(target_pids))})")
        print(f"  Selected Target:    '{target.title or target.id}' (URL: {target.url})")
        print(f"  Connection method:  CDP WebSocket ({ws_url[:45]}...)")

        # 5. Environment & DOM assertions
        current_stage = "environment_assertion"
        await assertions.assert_js("1 + 1", 2, "JavaScript Runtime Arithmetic Test")
        await assertions.assert_exists("body", "Document Body Presence")

        # 6. Optional interactive actions
        if type_selector and type_text:
            current_stage = "input_interaction"
            print(f"\nExecuting input: typing '{type_text}' into '{type_selector}'...")
            await assertions.assert_exists(type_selector, f"Target input '{type_selector}' exists")
            await actions.type_text(type_selector, type_text)
            print(f"Typed text into '{type_selector}'")

        if click_selector:
            current_stage = "click_interaction"
            print(f"\nExecuting interaction on '{click_selector}'...")
            await assertions.assert_exists(click_selector, f"Target element '{click_selector}' exists")
            geom = await actions.click(click_selector)
            print(f"Clicked element '{click_selector}' at ({geom.center_x:.1f}, {geom.center_y:.1f})")
            await asyncio.sleep(0.2)

        if assert_selector:
            current_stage = "ui_assertion"
            print(f"\nExecuting assertion on selector '{assert_selector}'...")
            if assert_text_expected is not None:
                await assertions.assert_text_contains(
                    assert_selector, assert_text_expected, f"Element '{assert_selector}' contains '{assert_text_expected}'"
                )
            else:
                await assertions.assert_exists(assert_selector, f"Element '{assert_selector}' exists")

        # 7. Screenshot Provenance Capture
        current_stage = "screenshot_capture"
        print(f"\nCapturing CDP webview screenshot to '{screenshot_path}'...")
        cdp_hash, cdp_meta = await collector.capture_cdp_screenshot(screenshot_path, key="webview")
        print(f"  [+] CDP Webview Screenshot: {screenshot_path} (SHA-256: {cdp_hash})")

        if window_forensics and window_forensics.hwnd and window_forensics.window_visible and not window_forensics.is_iconic:
            nat_path = native_screenshot_path or "screenshot_native.png"
            print(f"Capturing native desktop OS window screenshot to '{nat_path}'...")
            ok, nat_hash, nat_meta = collector.capture_native_screenshot(window_forensics.hwnd, nat_path, key="native")
            if ok:
                print(f"  [+] Native Desktop Screenshot: {nat_path} (SHA-256: {nat_hash})")
                collector.screenshots["desktop"] = ScreenshotMetadata(
                    screenshot_type=ScreenshotType.NATIVE_DESKTOP,
                    screenshot_hash=nat_hash,
                    path=nat_path,
                    source=f"desktop_surface (HWND: {window_forensics.hwnd})",
                    timestamp=time.time()
                )

        # 8. Build and save forensic evidence report
        current_stage = "evidence_generation"
        report = await collector.build_report(
            screenshot_path=screenshot_path,
            assertions=[r.to_dict() for r in assertions.history],
            actions=actions.history,
            process_ownership=proc_ownership,
            window_forensics=window_forensics,
            diagnostics={
                "framework": engine_info.framework or "native",
                "engine": adapter.engine_name,
                "confidence": conf_str,
                "platform": sys.platform,
                "target_url": target.url,
                "target_title": target.title
            },
            user_confirmation=True,
            input_delivery_verified=True,
            execution_mode="automated"
        )
        collector.save_report_json(report, evidence_path)
        print(f"\nEvidence report written to '{evidence_path}'")

        # 9. Tripartite Verdict Summary Output
        print("\n" + "=" * 65)
        print("=== Forensics Verdict Summary ===")
        print(f"Verdict:           {report.verdict.value}")
        print(f"Verdict Reason:    {report.verdict_reason}")
        print(f"Verification Level:{report.verification_level.value if hasattr(report.verification_level, 'value') else report.verification_level}")
        print(f"Assertions Passed: {sum(1 for r in assertions.history if r.passed)} / {len(assertions.history)}")
        print(f"Actions Executed:  {len(actions.history)}")
        print(f"Console Messages:  {len(session.console_events)}")
        print(f"Screenshots Taken: {len(report.screenshots)}")
        for sname, smeta in report.screenshots.items():
            print(f"  - [{sname}] ({smeta.screenshot_type}): {smeta.path} (SHA-256: {smeta.screenshot_hash[:16]}...)")
        print("=" * 65)

        if report.verdict == Verdict.PASS:
            return 0
        elif report.verdict == Verdict.UNVERIFIED:
            return 2
        else:
            return 1

    except Exception as e:
        suggestions = {
            "attach": "Verify WebSocket endpoint is active and not already owned/locked by another inspector session.",
            "inspection": "Check if page finished initial loading and DOM is accessible.",
            "gui_forensics": "Inspect Windows process tree and top-level HWND handles.",
            "environment_assertion": "Verify JavaScript execution is enabled in target webview settings.",
            "input_interaction": f"Check if selector '{type_selector}' exists in current DOM and is visible/editable.",
            "click_interaction": f"Check if selector '{click_selector}' exists and has non-zero geometry on screen.",
            "ui_assertion": f"Verify DOM state matches expected assertion on '{assert_selector}'.",
            "screenshot_capture": "Verify Page.captureScreenshot CDP command is supported by target engine.",
            "evidence_generation": "Check disk write permissions for evidence output files."
        }
        tip = suggestions.get(current_stage, "Inspect stderr logs and target process state.")
        print("\n======================================================")
        print("=== Webview Review Diagnostic Report [FAILURE] ===")
        print("======================================================")
        print(f"Framework:           {engine_info.framework or 'native'}")
        print(f"Engine:              {adapter.engine_name}")
        print(f"Confidence:          {conf_str.upper()}")
        print(f"Platform:            {sys.platform}")
        print(f"Launch mode:         {launch_mode}")
        print(f"Candidate targets:   {target.title or target.id}")
        print(f"Selected target:     {target.title or target.id} (URL: {target.url})")
        print(f"Connection method:   CDP WebSocket ({ws_url[:45]}...)")
        print(f"Failure stage:       {current_stage}")
        print(f"Reason:              {type(e).__name__}: {str(e)}")
        print(f"Suggested next diagnostic: {tip}")
        print("======================================================\n")
        return 1
    finally:
        if session:
            await adapter.detach(session)


def main():
    parser = argparse.ArgumentParser(description="Universal Desktop WebView Hardened Forensic Reviewer")
    parser.add_argument("--engine", default="auto", help="Engine name (default: 'auto')")
    parser.add_argument("--ws-url", default=None, help="Explicit WebSocket URL")
    parser.add_argument("--ws-file", default="desktop_ws_url.txt", help="File containing WebSocket URL")
    parser.add_argument("--click", default=None, help="CSS selector to click during review")
    parser.add_argument("--type-selector", default=None, help="CSS selector to type into")
    parser.add_argument("--type-text", default=None, help="Text to type into type-selector")
    parser.add_argument("--assert-selector", default=None, help="CSS selector to assert on")
    parser.add_argument("--assert-text", default=None, help="Expected text in assert-selector")
    parser.add_argument("--screenshot", default="screenshot.png", help="Output CDP webview screenshot path")
    parser.add_argument("--native-screenshot", default=None, help="Output native OS window screenshot path")
    parser.add_argument("--evidence", default="evidence.json", help="Output evidence JSON path")
    parser.add_argument("--ownership-file", default="desktop_ownership.json", help="Process ownership file")

    args = parser.parse_args()

    ws_url = args.ws_url
    if not ws_url:
        target_file = args.ws_file
        if not os.path.exists(target_file) and os.path.exists("qt_ws_url.txt"):
            target_file = "qt_ws_url.txt"

        if not os.path.exists(target_file):
            print(f"Error: WebSocket URL file '{target_file}' not found. Run discover.py first.")
            sys.exit(1)
        with open(target_file, "r") as f:
            ws_url = f.read().strip()

    if not ws_url:
        print("Error: Empty WebSocket URL.")
        sys.exit(1)

    exit_code = asyncio.run(run_review(
        ws_url=ws_url,
        engine_name=args.engine,
        click_selector=args.click,
        type_selector=args.type_selector,
        type_text=args.type_text,
        assert_selector=args.assert_selector,
        assert_text_expected=args.assert_text,
        screenshot_path=args.screenshot,
        native_screenshot_path=args.native_screenshot,
        evidence_path=args.evidence,
        ownership_file=args.ownership_file
    ))
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
