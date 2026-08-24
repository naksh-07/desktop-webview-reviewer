"""
Universal launcher CLI for desktop webview applications.
"""

import argparse
import os
import sys

# Ensure parent directory is on sys.path for direct script execution
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from detectors.engine_detector import EngineDetector
from launchers.process_launcher import ProcessLauncher


def main():
    parser = argparse.ArgumentParser(description="Universal Desktop WebView App Launcher")
    parser.add_argument("executable", help="Path to desktop app executable or Python script")
    parser.add_argument("app_args", nargs="*", help="Optional arguments to pass to the desktop app")
    parser.add_argument("--engine", default=None, help="Force specific engine (e.g. 'qtwebengine')")
    parser.add_argument("--port", type=int, default=9222, help="Remote debugging port (default: 9222)")
    parser.add_argument("--pid-file", default="desktop_app.pid", help="File to store process PID")
    parser.add_argument("--init-delay", type=float, default=2.0, help="Seconds to wait after launch")
    parser.add_argument("--cwd", default=None, help="Working directory for the launched process")
    parser.add_argument("--env", action="append", default=[], help="Additional environment variable KEY=VALUE")

    args = parser.parse_args()

    env_overrides = {}
    for ev in args.env:
        if "=" in ev:
            k, v = ev.split("=", 1)
            env_overrides[k] = v

    adapter = EngineDetector.resolve_adapter(engine_name_or_hint=args.engine, target_path_or_pid=args.executable)
    print(f"Using engine adapter: '{adapter.engine_name}'")
    print(f"Launching {args.executable} on debug port {args.port}...")

    try:
        pid = ProcessLauncher.launch(
            executable_or_script=args.executable,
            args=args.app_args,
            adapter=adapter,
            port=args.port,
            pid_file=args.pid_file,
            init_delay=args.init_delay,
            cwd=args.cwd,
            env_overrides=env_overrides if env_overrides else None
        )
        print(f"Application launched successfully with PID: {pid}")
        print(f"PID saved to {args.pid_file}")
    except Exception as e:
        print(f"Failed to launch application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
