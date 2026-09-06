"""
Universal target discovery CLI.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capabilities import CapabilityRegistry
from core.models import TargetCriteria
from core.discovery import TargetDiscovery
from detectors.engine_detector import EngineDetector


def main():
    parser = argparse.ArgumentParser(description="Universal Desktop WebView Target Discovery")
    parser.add_argument("--engine", default=None, help="Engine name (default: auto-detected or qtwebengine)")
    parser.add_argument("--host", default="127.0.0.1", help="Debug host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9222, help="Debug port (default: 9222)")
    parser.add_argument("--timeout", type=float, default=15.0, help="Polling timeout in seconds (default: 15.0)")
    parser.add_argument("--type", default="page", help="Target type filter (default: 'page')")
    parser.add_argument("--title", default=None, help="Filter by title substring")
    parser.add_argument("--url", default=None, help="Filter by URL substring")
    parser.add_argument("--out-ws", default="desktop_ws_url.txt", help="File to write selected WebSocket URL")

    args = parser.parse_args()

    adapter = EngineDetector.resolve_adapter(engine_name_or_hint=args.engine)
    engine_info = adapter.get_engine_info()

    print(f"Target Discovery for engine: '{adapter.engine_name}'")
    print(f"Polling http://{args.host}:{args.port}/json/list (timeout: {args.timeout}s)...")

    targets = adapter.discover_targets(host=args.host, port=args.port, timeout=args.timeout)
    ownership_file = "desktop_ownership.json"
    launch_mode = "launched_by_reviewer" if os.path.exists(ownership_file) else "attached_external"
    conf_str = engine_info.confidence.value if hasattr(engine_info.confidence, "value") else str(engine_info.confidence)

    if not targets:
        print("\n======================================================")
        print("=== Webview Review Diagnostic Report [FAILURE] ===")
        print("======================================================")
        print(f"Framework:           {engine_info.framework or 'native'}")
        print(f"Engine:              {adapter.engine_name}")
        print(f"Confidence:          {conf_str.upper()}")
        print(f"Platform:            {sys.platform}")
        print(f"Launch mode:         {launch_mode}")
        print(f"Candidate targets:   None discovered")
        print(f"Selected target:     None")
        print(f"Connection method:   HTTP Poll (http://{args.host}:{args.port}/json/list)")
        print(f"Failure stage:       discovery")
        print(f"Reason:              No debugging endpoints found on http://{args.host}:{args.port} after {args.timeout}s")
        print(f"Suggested next diagnostic: Check if application process is running and was started with remote debugging enabled (e.g. QTWEBENGINE_REMOTE_DEBUGGING={args.port}, --remote-debugging-port={args.port}, or WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS). Verify port {args.port} is not occupied by an unrelated service.")
        print("======================================================\n")
        sys.exit(1)

    print(f"\nFound {len(targets)} total target(s):")
    for i, t in enumerate(targets):
        print(f"  [{i}] ID: {t.id} | Type: {t.type} | Title: '{t.title}' | URL: {t.url}")

    criteria = TargetCriteria(
        target_type=args.type,
        title_pattern=args.title,
        url_pattern=args.url
    )
    selected = adapter.select_target(targets, criteria)

    if not selected or not selected.websocket_endpoint:
        print("\n======================================================")
        print("=== Webview Review Diagnostic Report [FAILURE] ===")
        print("======================================================")
        print(f"Framework:           {engine_info.framework or 'native'}")
        print(f"Engine:              {adapter.engine_name}")
        print(f"Confidence:          {conf_str.upper()}")
        print(f"Platform:            {sys.platform}")
        print(f"Launch mode:         {launch_mode}")
        print(f"Candidate targets:\n{TargetDiscovery.format_ranking_diagnostics(targets, selected)}")
        print(f"Selected target:     None")
        print(f"Connection method:   HTTP Poll (http://{args.host}:{args.port}/json/list)")
        print(f"Failure stage:       target_selection")
        print(f"Reason:              No candidate target matched criteria (type='{args.type}', title='{args.title}', url='{args.url}')")
        print(f"Suggested next diagnostic: Inspect the listed candidate targets above and adjust the --type, --title, or --url filters.")
        print("======================================================\n")
        sys.exit(1)

    print(f"\nSelected Target:")
    print(f"  ID: {selected.id}")
    print(f"  Title: {selected.title}")
    print(f"  URL: {selected.url}")
    print(f"  WebSocket URL: {selected.websocket_endpoint}")

    with open(args.out_ws, "w") as f:
        f.write(selected.websocket_endpoint)
    print(f"Saved WebSocket URL to {args.out_ws}")

    # Also save to qt_ws_url.txt if engine is qtwebengine for backward compatibility
    if adapter.engine_name == "qtwebengine" and args.out_ws != "qt_ws_url.txt":
        try:
            with open("qt_ws_url.txt", "w") as f:
                f.write(selected.websocket_endpoint)
        except Exception:
            pass

    print("\n" + CapabilityRegistry.format_capability_summary(engine_info))


if __name__ == "__main__":
    main()
