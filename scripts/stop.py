"""
Universal process terminator and resource cleaner.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.cleanup import ProcessCleanup


def main():
    parser = argparse.ArgumentParser(description="Universal Desktop WebView Process Terminator")
    parser.add_argument("pid", nargs="?", type=int, default=None, help="Process ID to terminate")
    parser.add_argument("--pid-file", default="desktop_app.pid", help="File containing PID")
    parser.add_argument("--ownership-file", default="desktop_ownership.json", help="File containing process ownership metadata")
    parser.add_argument("--clean-files", action="store_true", default=True, help="Clean up state files")

    args = parser.parse_args()

    pid = args.pid
    if pid is not None:
        print(f"Stopping process tree for explicit PID: {pid}...")
        success = ProcessCleanup.terminate_process_tree(pid)
        if success:
            print("Process tree terminated successfully.")
        else:
            print("Warning: Process termination completed with errors or PID was already gone.")
        if args.clean_files:
            ProcessCleanup.clean_state_files()
            print("Temporary state files cleaned.")
        return

    # Use safe_cleanup from ownership file / PID file
    target_pid_file = args.pid_file
    if not os.path.exists(target_pid_file) and os.path.exists("qt_app.pid"):
        target_pid_file = "qt_app.pid"

    print("Running safe cleanup of reviewer processes and state files...")
    success = ProcessCleanup.safe_cleanup(
        pid_file=target_pid_file,
        ownership_file=args.ownership_file
    )
    if success:
        print("Cleanup completed successfully.")
    else:
        print("Warning: Cleanup finished with warnings.")


if __name__ == "__main__":
    main()

