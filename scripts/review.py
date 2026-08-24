"""
Automated review & verification script.
Inspects DOM, evaluates JS, interacts with elements, captures screenshots, and produces evidence reports.
"""

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from typing import Optional

from core.actions import WebviewActions
from core.assertions import WebviewAssertions
from core.evidence import EvidenceCollector
from core.models import ProcessOwnership, Target, VerificationLevel
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
    evidence_path: str = "evidence.json",
    ownership_file: str = "desktop_ownership.json"
):
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

    print("\n" + "=" * 60)
    print("=== Universal Desktop WebView Automated Review ===")
    print("=" * 60)
    print(f"Connecting reviewer to: {ws_url}")
    print(f"Engine: {adapter.engine_name} | Framework: {engine_info.framework or 'native'}")

    current_stage = "attach"
    ownership_file = "desktop_ownership.json"
    launch_mode = "launched_by_reviewer" if os.path.exists(ownership_file) else "attached_external"
    conf_str = engine_info.confidence.value if hasattr(engine_info.confidence, "value") else str(engine_info.confidence)

    # Process ownership metadata
    proc_ownership: Optional[ProcessOwnership] = None
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
        except Exception:
            pass

    session = None
    try:
        current_stage = "attach"
        session = await adapter.attach(target)
        actions = adapter.create_actions(session)
        assertions = adapter.create_assertions(session)
        collector = adapter.create_evidence_collector(session)

        # 1. Inspect title and url
        current_stage = "inspection"
        title = await session.evaluate_js("document.title")
        url = await session.evaluate_js("window.location.href")
        target.title = str(title or "")
        target.url = str(url or "")
        print(f"Target Title: '{target.title}' | URL: '{target.url}'")

        # Session Diagnostics
        print("\nSession Diagnostics:")
        print(f"  Detected framework: {engine_info.framework or 'native'}")
        print(f"  Detected engine:    {adapter.engine_name}")
        print(f"  Confidence:         {conf_str.upper()}")
        print(f"  Platform:           {sys.platform}")
        print(f"  Launch mode:        {launch_mode}")
        print(f"  Selected Target:    {target.title or target.id} (URL: {target.url})")
        print(f"  Connection method:  CDP WebSocket ({ws_url[:45]}...)")
        print(f"  Verification Level: RUNTIME_VERIFIED")

        # 2. Basic environment assertions
        current_stage = "environment_assertion"
        await assertions.assert_js("1 + 1", 2, "JavaScript Runtime Arithmetic Test")
        await assertions.assert_exists("body", "Document Body Presence")

        # 3. Optional interactive actions
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
                await assertions.assert_text_contains(assert_selector, assert_text_expected, f"Element '{assert_selector}' contains '{assert_text_expected}'")
            else:
                await assertions.assert_exists(assert_selector, f"Element '{assert_selector}' exists")

        # 4. Capture screenshot & validate PNG header
        current_stage = "screenshot_capture"
        print(f"\nCapturing screenshot to '{screenshot_path}'...")
        sha256 = await collector.capture_screenshot_file(screenshot_path)
        print(f"Screenshot verified (SHA-256: {sha256})")

        # 5. Build and save evidence report
        current_stage = "evidence_generation"
        report = await collector.build_report(
            screenshot_path=screenshot_path,
            assertions=[r.to_dict() for r in assertions.history],
            actions=actions.history,
            process_ownership=proc_ownership,
            diagnostics={
                "framework": engine_info.framework or "native",
                "engine": adapter.engine_name,
                "confidence": conf_str,
                "platform": sys.platform,
                "target_url": target.url,
                "target_title": target.title
            },
            verification_level=VerificationLevel.RUNTIME_VERIFIED
        )
        collector.save_report_json(report, evidence_path)
        print(f"Evidence report written to '{evidence_path}'")

        print("\n" + "=" * 60)
        print("=== Review Summary ===")
        print(f"Assertions Passed: {sum(1 for r in assertions.history if r.passed)} / {len(assertions.history)}")
        print(f"Actions Executed:  {len(actions.history)}")
        print(f"Console Messages:  {len(session.console_events)}")
        print("Verification:      RUNTIME_VERIFIED")
        print("=" * 60)

    except Exception as e:
        suggestions = {
            "attach": "Verify WebSocket endpoint is active and not already owned/locked by another inspector session.",
            "inspection": "Check if page finished initial loading and DOM is accessible.",
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
        raise
    finally:
        if session:
            await adapter.detach(session)


def main():
    parser = argparse.ArgumentParser(description="Universal Desktop WebView Automated Reviewer")
    parser.add_argument("--engine", default="auto", help="Engine name (default: 'auto')")
    parser.add_argument("--ws-url", default=None, help="Explicit WebSocket URL")
    parser.add_argument("--ws-file", default="desktop_ws_url.txt", help="File containing WebSocket URL")
    parser.add_argument("--click", default=None, help="CSS selector to click during review")
    parser.add_argument("--type-selector", default=None, help="CSS selector to type into")
    parser.add_argument("--type-text", default=None, help="Text to type into type-selector")
    parser.add_argument("--assert-selector", default=None, help="CSS selector to assert on")
    parser.add_argument("--assert-text", default=None, help="Expected text in assert-selector")
    parser.add_argument("--screenshot", default="screenshot.png", help="Output screenshot path")
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

    asyncio.run(run_review(
        ws_url=ws_url,
        engine_name=args.engine,
        click_selector=args.click,
        type_selector=args.type_selector,
        type_text=args.type_text,
        assert_selector=args.assert_selector,
        assert_text_expected=args.assert_text,
        screenshot_path=args.screenshot,
        evidence_path=args.evidence,
        ownership_file=args.ownership_file
    ))


if __name__ == "__main__":
    main()

